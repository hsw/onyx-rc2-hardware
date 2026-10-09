// SPDX-License-Identifier: MIT
// ImportKallsymsRaw.java (board-file version; takes a function list instead of an address range) --
// Ghidra headless postScript for the stock RC2 kernel Image imported as a raw binary
// (BinaryLoader, base 0xc0408000, ARM:LE:32:v7, -noanalysis).
// Args: <kallsyms.txt> <list>   list: one kallsyms name or hex VA per line (# comments allowed)
//   1. splits the single "ram" block into text / rodata (read-only, so literal pools and string pointers fold)
//      and data (writable), and adds an uninitialised .bss block after the Image (up to 0xc1600000);
//   2. puts a label on every kallsyms symbol (all types);
//   3. disassembles and creates a function at every listed symbol, then creates functions at the direct call
//      targets of those functions (one level, kallsyms symbols only) so calls print with names.
// Nothing is executed; the Image is only read.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.nio.file.*;
import java.util.*;

public class ImportKallsymsRaw extends GhidraScript {
  static final long TEXT_END = 0xc0a02000L;     // __start_rodata
  static final long RO_END = 0xc0a52818L;       // _etext (rodata, ksymtab, kstrtab ...)
  static final long BSS_END = 0xc1600000L;

  Address A(long v) { return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(v); }

  public void run() throws Exception {
    String[] args = getScriptArgs();
    Set<String> want = new HashSet<>();
    for (String l : Files.readAllLines(Paths.get(args[1]))) {
      l = l.replaceAll("#.*", "").trim();
      if (!l.isEmpty()) want.add(l);
    }
    Memory mem = currentProgram.getMemory();
    MemoryBlock b = mem.getBlock(A(0xc0408000L));
    long imgEnd = b.getEnd().getOffset() + 1;
    if (b.getStart().getOffset() != 0xc0408000L) throw new Exception("unexpected base " + b.getStart());
    mem.split(b, A(TEXT_END));
    MemoryBlock ro = mem.getBlock(A(TEXT_END));
    mem.split(ro, A((RO_END + 0xfff) & ~0xfffL));
    MemoryBlock text = mem.getBlock(A(0xc0408000L));
    text.setName("text"); text.setWrite(false); text.setExecute(true);
    ro = mem.getBlock(A(TEXT_END));
    ro.setName("rodata"); ro.setWrite(false); ro.setExecute(false);
    MemoryBlock data = mem.getBlock(A((RO_END + 0xfff) & ~0xfffL));
    data.setName("data"); data.setWrite(true); data.setExecute(false);
    long bssStart = (imgEnd + 0xfff) & ~0xfffL;
    MemoryBlock bss = mem.createUninitializedBlock("bss", A(bssStart), BSS_END - bssStart, false);
    bss.setRead(true); bss.setWrite(true);
    println("ImportKallsymsRaw: image end 0x" + Long.toHexString(imgEnd) + ", bss 0x" + Long.toHexString(bssStart));

    SymbolTable st = currentProgram.getSymbolTable();
    List<long[]> funcs = new ArrayList<>();
    Map<Long, String> names = new HashMap<>();
    int nl = 0;
    for (String l : Files.readAllLines(Paths.get(args[0]))) {
      if (l.startsWith("#")) continue;
      String[] p = l.trim().split("\\s+");
      if (p.length < 3) continue;
      long a = Long.parseLong(p[0], 16);
      Address ad = A(a);
      if (!mem.contains(ad)) continue;
      String n = p[2].replace(' ', '_');
      try { st.createLabel(ad, n, SourceType.IMPORTED); nl++; } catch (Exception e) { }
      char t = p[1].charAt(0);
      if (t == 't' || t == 'T' || t == 'W') {
        if (!names.containsKey(a)) names.put(a, n);
        if (want.contains(n) || want.contains(String.format("%08x", a))) funcs.add(new long[] { a });
      }
    }
    println("ImportKallsymsRaw: " + nl + " labels, " + funcs.size() + " listed functions");
    FunctionManager fm = currentProgram.getFunctionManager();
    Set<Long> callees = new TreeSet<>();
    for (long[] f : funcs) {
      Function fn = makeFunc(f[0], names.get(f[0]));
      if (fn == null) continue;
      for (Instruction ins : currentProgram.getListing().getInstructions(fn.getBody(), true)) {
        for (Reference r : ins.getReferencesFrom()) {
          if (r.getReferenceType().isCall() || r.getReferenceType().isJump()) {
            long t = r.getToAddress().getOffset();
            if (names.containsKey(t)) callees.add(t);
          }
        }
      }
    }
    int nc = 0;
    for (long t : callees) if (makeFunc(t, names.get(t)) != null) nc++;
    println("ImportKallsymsRaw: " + nc + " callee functions");
  }

  Function makeFunc(long a, String n) throws Exception {
    Address ad = A(a);
    FunctionManager fm = currentProgram.getFunctionManager();
    Function f = fm.getFunctionAt(ad);
    if (f != null) return f;
    if (currentProgram.getListing().getInstructionAt(ad) == null) {
      DisassembleCommand dc = new DisassembleCommand(ad, null, true);
      dc.applyTo(currentProgram, monitor);
    }
    f = createFunction(ad, n);
    if (f == null) printerr("ImportKallsymsRaw: cannot create function " + n + " @" + ad);
    else f.setName(n, SourceType.IMPORTED);
    return f;
  }
}
