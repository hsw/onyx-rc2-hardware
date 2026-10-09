#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Recover the kallsyms table of a raw ARM Linux 3.0 kernel Image (no ELF, no System.map).

usage: python3 -I extract_kallsyms.py IMAGE OUT.txt
       OUT.txt gets one 'VA type name' line per symbol (hex VA).

Heuristic: find kallsyms_token_index (256 increasing u16 starting at 0), the token table before it, then walk back
to markers, names, num_syms and addresses. Written for the stock RC2 kernel Image (2017-11-07 build, 38 721 symbols,
VA = file offset + 0xc0408000); on another Image check the offsets it prints on stderr.
"""
import struct,sys
d=open(sys.argv[1],'rb').read()
n=len(d)
# find token_index: 256 u16 starting with 0, increasing
cands=[]
for off in range(0,n-512,2):
    if d[off]!=0 or d[off+1]!=0: continue
    a=struct.unpack_from('<256H',d,off)
    if a[1]==0 or a[1]>8: continue
    ok=all(a[i]<a[i+1] for i in range(255)) and a[255]<2000
    if not ok: continue
    # find table start
    for T in range(off-a[255]-40, off-a[255]):
        if T<0: continue
        good=True
        for i in range(255):
            s=T+a[i]; e=T+a[i+1]-1
            if d[e]!=0 or 0 in d[s:e]: good=False;break
        if good:
            cands.append((off,T,a));break
print('cands',[(hex(c[0]),hex(c[1])) for c in cands],file=sys.stderr)
idx,T,a=[c for c in cands if c[1]%4==0][0]
tokens=[]
for i in range(256):
    s=T+a[i]; e=d.index(b'\0',s); tokens.append(d[s:e].decode('latin1'))
# markers precede T: u32 array, markers[0]==0, increasing. walk back
p=T-4
while d[p:p+4]==b'\0\0\0\0' and struct.unpack_from('<I',d,p-4)[0]==0: p-=4
# p now points to last marker (maybe padding zeros); walk back while decreasing
m=[]
q=T-4
# skip trailing zero padding
while struct.unpack_from('<I',d,q)[0]==0: q-=4
while True:
    v=struct.unpack_from('<I',d,q)[0]
    m.append(v)
    if v==0: break
    q-=4
markers_off=q; m=m[::-1]
print('markers',hex(markers_off),len(m),file=sys.stderr)
# names end at markers_off; names start: num_syms precedes. Find addresses run backwards
# approximate num_syms from markers: between (len(m)-1)*256+1 .. len(m)*256
# names start such that decoding n syms ends at markers_off: search num_syms field
for ns_off in range(markers_off-4, max(0,markers_off-4000000), -4):
    ns=struct.unpack_from('<I',d,ns_off)[0]
    if (len(m)-1)*256 < ns <= len(m)*256:
        # names begins at ns_off+4 (maybe aligned to 16?)
        for start in (ns_off+4, (ns_off+4+15)&~15):
            p=start;okk=True
            for i in range(ns):
                if p>=markers_off: okk=False;break
                p+=d[p]+1
            if okk and markers_off-16<p<=markers_off:
                num=ns;names_off=start;break
        else: continue
        break
print('num_syms',num,hex(ns_off),hex(names_off),file=sys.stderr)
# addresses: num u32 ending before ns_off (aligned)
addr_end=ns_off
while struct.unpack_from('<I',d,addr_end-4)[0]==0: addr_end-=4
addr_off=addr_end-4*num
addrs=struct.unpack_from('<%dI'%num,d,addr_off)
print('addr_off',hex(addr_off),hex(addrs[0]),hex(addrs[-1]),file=sys.stderr)
p=names_off
out=[]
for i in range(num):
    l=d[p]; s=''.join(tokens[b] for b in d[p+1:p+1+l]); p+=l+1
    out.append('%08x %s %s'%(addrs[i],s[0],s[1:]))
open(sys.argv[2],'w').write('\n'.join(out)+'\n')
