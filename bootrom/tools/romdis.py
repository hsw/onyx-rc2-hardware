#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Annotated ARM disassembly of the RK3026 BootROM dump (VMA 0 = ROM alias at boot).
usage: romdis.py rom.bin > rom-annot.lst"""
import sys, struct, capstone
from capstone.arm import ARM_OP_MEM, ARM_OP_IMM, ARM_REG_PC
P = {0x10080000:'IMEM',0x10100000:'ROM',0x10200000:'CRYPTO',0x10214000:'SDMMC0',0x10218000:'SDIO',
     0x1021c000:'EMMC',0x10500000:'NANDC',0x10180000:'USBOTG',0x101c0000:'USBHOST',0x20000000:'CRU',
     0x20008000:'GRF',0x20004000:'DDR_PCTL',0x2000a000:'DDR_PHY',0x2004c000:'WDT',0x20044000:'TIMER0',
     0x20046000:'TIMER1',0x20060000:'UART0',0x20064000:'UART1',0x20068000:'UART2',0x20074000:'SPI',
     0x2007c000:'GPIO0',0x20080000:'GPIO1',0x20084000:'GPIO2',0x20088000:'GPIO3',0x20090000:'EFUSE',
     0x1013c000:'SCU',0x1013d000:'GICD',0x1013c100:'GICC',0x20078000:'DMAC',0x20020000:'DBG',
     0x10128000:'CPU_AXI',0x10300000:'PERI_AXI',0x2006c000:'SARADC',0x20070000:'I2C0'}
def name(v):
    best=None
    for b,n in P.items():
        if b<=v<b+0x4000 and (best is None or b>best[0]): best=(b,n)
    if best: return '%s+0x%x'%(best[1],v-best[0])
    return None
data=open(sys.argv[1],'rb').read()
end=int(sys.argv[2],0) if len(sys.argv)>2 else len(data)
md=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_ARM); md.detail=True; md.skipdata=True
calls={}
insns=list(md.disasm(data[:end],0))
for i in insns:
    if i.mnemonic in('bl','blx') and i.operands and i.operands[0].type==ARM_OP_IMM:
        calls.setdefault(i.operands[0].imm,[]).append(i.address)
for i in insns:
    if i.address in calls:
        print('\n; ===== sub_%04x  (called from %s)'%(i.address,','.join('%x'%c for c in calls[i.address][:8])))
    c=''
    if i.id!=0 and i.operands:
        for op in i.operands:
            if op.type==ARM_OP_MEM and op.mem.base==ARM_REG_PC and i.mnemonic.startswith('ldr'):
                a=i.address+8+op.mem.disp
                if 0<=a<len(data)-3:
                    v=struct.unpack_from('<I',data,a)[0]; n=name(v)
                    c+=' =0x%x%s'%(v,(' '+n) if n else '')
    print('%05x: %08x  %-8s %s%s'%(i.address,struct.unpack_from('<I',data,i.address)[0] if i.size==4 else 0,i.mnemonic,i.op_str,(' ;'+c) if c else ''))
