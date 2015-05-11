#!/usr/bin/env python3

import numpy
from os import path
import os
import random
import re
import subprocess
import sys
import time

TESTDIR = path.realpath(path.dirname(__file__))

if "LIBALLOCS_BASE" in os.environ:
    LIBALLOCS_BASE = os.environ["LIBALLOCS_BASE"]
else:
    LIBALLOCS_BASE = path.join(TESTDIR, "../../liballocs")
LIBALLOCS_BASE = path.realpath(LIBALLOCS_BASE)

if "LIBCRUNCH_BASE" in os.environ:
    LIBCRUNCH_BASE = os.environ["LIBCRUNCH_BASE"]
else:
    LIBCRUNCH_BASE = path.join(LIBALLOCS_BASE, "../libcrunch")
LIBCRUNCH_BASE = path.realpath(LIBCRUNCH_BASE)

CLEAN_EXTS = ["-allocsites.c", "-allocsites.so", "-types.c", "-types.c.log.gz",
              "-types.so", ".allocs", ".allocs.rej", ".allocstubs.c",
              ".allocstubs.i", ".allocstubs.o", ".cil.c", ".cil.i", ".cil.s",
              ".i", ".i.allocs", ".makelog", ".o", ".o.fixuplog", ".objallocs",
              ".s", ".srcallocs", ".srcallocs.rej"]

DEFAULT_SUMMARY_VALUE = 0

def runWithEnv(cmd, env = {}):
    assigns = ["%s='%s'" % (e, env[e]) for e in env]
    print(" ".join(assigns + cmd))
    wholeEnv = dict(os.environ)
    wholeEnv.update(env)

    startTime = time.time()

    proc = subprocess.Popen(cmd, stdout = subprocess.PIPE,
                            stderr =  subprocess.PIPE, env = wholeEnv,
                            cwd = TESTDIR)
    (stdout, stderr) = proc.communicate()
    returncode = proc.wait()

    elapsedTime = time.time() - startTime

    stdout = stdout.decode()
    stderr = stderr.decode()

    print("Command exited with status", returncode, ":")
    print("   ", " ".join(assigns + cmd))
    print("stdout:")
    print(stdout)
    print("\nstderr:")
    print(stderr)

    return (returncode, stdout, stderr, elapsedTime)

def parseSummaryLine(line):
    found = False
    ret = {}
    def check(name, match):
        nonlocal found, ret
        if found: # Avoid rechecking once we've found a match for this line
            return
        m = re.match(match + ":?\\s+([0-9]+)", line)
        if m:
            found = True
            ret = {name: int(m.group(1))}

    # Crunch summary outputs
    check("c.begun", "checks begun")
    check("c.aborted_typename", "checks aborted for bad typename")
    check("c.remaining", "checks remaining")
    check("c.lazy_heap", "of which did lazy heap type assignment")
    check("c.failed_alloc", "checks failed inside allocation functions")
    check("c.failed_other", "checks failed otherwise")
    check("c.failed_suppression", "of which user suppression list matched")
    check("c.nontriv", "checks nontrivially passed")
    check("c.hit_cache", "of which hit __is_a cache")

    # Allocs summary outputs
    check("a.abort_heap", "queries aborted for unindexed heap")
    check("a.abort_stack", "queries aborted for unknown stackframes")
    check("a.abort_static", "queries aborted for unknown static obj")
    check("a.abort_storage", "queries aborted for unknown storage")
    check("a.heap", "queries handled by heap case")
    check("a.stack", "queries handled by stack case")
    check("a.static", "queries handled by static case")

    return ret

# Parse the summary generated by libcrunch and liballocs
def parseSummary(output):
    lines = output.splitlines()
    ret = {}
    for l in lines:
        ret.update(parseSummaryLine(l.strip()))
    return ret

class Test:
    def build(self):
        self.clean()
        cmdout = runWithEnv(self.getBuildCmd(), self.getBuildEnv())
        self.buildTime = cmdout[3]
        return cmdout[0]

    def run(self):
        cmdout = runWithEnv(self.getRunCmd(), self.getRunEnv())
        self.runTime = cmdout[3]
        self.actualSummary = parseSummary(cmdout[2])
        return cmdout[0]

    def checkSummary(self):
        passed = True
        for key in self.correctSummary:
            if key not in self.actualSummary:
                print("Error: Summary value %s not reported, should be %d" %
                        (key, self.correctSummary[key]))
                passed = False
                continue
            if self.correctSummary[key] != self.actualSummary[key]:
                print("Error: Summary value %s should be '%s', got '%s'" %
                      (key, self.correctSummary[key], self.actualSummary[key]))
                passed = False

        # Everything else should be zero
        for key in self.actualSummary:
            if key not in self.correctSummary:
                if self.actualSummary[key] != DEFAULT_SUMMARY_VALUE:
                    print("Error: Summary value %s should be '%s', got '%s'" %
                          (key, DEFAULT_SUMMARY_VALUE,
                           self.actualSummary[key]))
                    passed = False
        return passed

    def getCleanFiles(self):
        return []

    def getBuildEnv(self):
        return {}

    def getRunEnv(self):
        return {}

    def clean(self):
        for f in self.getCleanFiles():
            if path.exists(f):
                os.unlink(f)

class AllocsTest(Test):
    def __init__(self, fname, buildEnv = {}, runEnv = {},
                 fail = False, flags = [], summary = {}):
        self.testName = path.splitext(fname)[0]
        self.src_fname = path.realpath(path.join(TESTDIR, fname))
        self.out_fname = path.splitext(self.src_fname)[0]
        self.buildEnv = buildEnv
        self.runEnv = runEnv
        self.shouldFail = fail
        self.flags = flags
        self.correctSummary = summary

    def getCompiler(self):
        return "clangallocscc"

    def getName(self):
        return self.testName

    def getBuildCmd(self):
        cmd = [self.getCompiler()]
        cmd += ["-std=c99", "-DUSE_STARTUP_BRK"]
        cmd += self.flags
        cmd += [self.src_fname, "-o", self.out_fname]
        return cmd

    def getBuildEnv(self):
        return self.buildEnv

    def getRunEnv(self):
        liballocs = path.join(LIBALLOCS_BASE, "lib/liballocs_preload.so")
        ld_preload = {"LD_PRELOAD": path.realpath(liballocs)}
        return dict(self.runEnv, **ld_preload)

    def getRunCmd(self):
        return [self.out_fname]

    def getCleanFiles(self):
        files = [self.out_fname + e for e in CLEAN_EXTS]
        files += [path.splitext(self.src_fname)[0] + e for e in CLEAN_EXTS]
        files += [self.out_fname]

        if "ALLOCSITES_BASE" in os.environ:
            sites = os.environ["ALLOCSITES_BASE"]
        else:
            sites = "/usr/lib/allocsites"
        sites = path.realpath(sites)
        sites = sites + path.realpath(self.out_fname)
        files += [sites + e for e in CLEAN_EXTS]

        return files

class StockAllocsTest(AllocsTest):
    def getBuildCmd(self):
        cmd = AllocsTest.getBuildCmd(self)
        # Without this argument there are "undefined reference to
        # `local_accessors'" errors.
        cmd = [cmd[0], "-gstrict-dwarf"] + cmd[1:]
        return cmd

    def getCompiler(self):
        return "allocscc"

    def getName(self):
        n = AllocsTest.getName(self)
        if n.startswith("broken/"):
            return "broken/stock" + n[6:]
        return "stock/" + n

class CrunchTest(AllocsTest):
    def getCompiler(self):
        return "clangcrunchcc"

    def getBuildCmd(self):
        cmd = [self.getCompiler()]
        cmd += ["-D_GNU_SOURCE", "-std=c99", "-DUSE_STARTUP_BRK"]
        cmd += ["-fno-eliminate-unused-debug-types"]
        cmd += ["-I" + path.join(LIBCRUNCH_BASE, "include")]
        cmd += ["-I" + path.join(LIBALLOCS_BASE, "include")]
        cmd += self.flags
        # CrunchCC has a bug where the allocsites can get lost if the source
        # filename is an absolute path. Make it relative to TESTDIR.
        src = path.relpath(self.src_fname, TESTDIR)
        cmd += [src, "-o", self.out_fname]
        return cmd

    def getRunEnv(self):
        liballocs = path.join(LIBCRUNCH_BASE, "lib/libcrunch_preload.so")
        ld_preload = {"LD_PRELOAD": path.realpath(liballocs)}
        return dict(self.runEnv, **ld_preload)

class StockCrunchTest(CrunchTest):
    def getBuildCmd(self):
        if False:
            cmd = [self.getCompiler()]
            cmd += ["-D_GNU_SOURCE", "-g3", "-gstrict-dwarf", "-std=c99"]
            cmd += ["-fno-eliminate-unused-debug-types"]
            cmd += ["-O2", "-DUSE_STARTUP_BRK"]
            cmd += ["-I" + path.join(LIBCRUNCH_BASE, "include")]
            cmd += ["-I" + path.join(LIBALLOCS_BASE, "include")]
            cmd += self.flags
            cmd += [self.src_fname, "-o", self.out_fname]
        cmd = CrunchTest.getBuildCmd(self)
        cmd = [cmd[0], "-gstrict-dwarf"] + cmd[1:]
        return cmd

    def getCompiler(self):
        return "crunchcc"

    def getName(self):
        n = CrunchTest.getName(self)
        if n.startswith("broken/"):
            return "broken/stock" + n[6:]
        return "stock/" + n

class CrunchMakefileTest(CrunchTest):
    def __init__(self, directory, summary = {}):
        self.directory = directory
        self.out_fname = path.join(directory, path.basename(directory))
        AllocsTest.__init__(self, self.out_fname + ".c", summary = summary)

    def getBuildCmd(self):
        cmd = ["make", "-C", path.join(TESTDIR, self.directory)]
        return cmd

    def getBuildEnv(self):
        return {"CC": "clangcrunchcc"}

    def getName(self):
        return self.directory

    def getCleanFiles(self):
        return []

class StockCrunchMakefileTest(CrunchMakefileTest):
    def getBuildEnv(self):
        return {"CC": "crunchcc"}

    def getName(self):
        return "stock/" + CrunchMakefileTest.getName(self)

def pkg_config(pkg):
    cmd = ["pkg-config", "--cflags", "--libs", pkg]
    ret = subprocess.check_output(cmd)
    ret = ret.decode()
    return ret.split()

def register_tests():
    tests = {}
    def add(t):
        assert isinstance(t, Test)
        name = t.getName()
        if name in tests:
            print("Error: Test '%s' already exists." % name)
        else:
            tests[t.getName()] = t

    def addAllocsTest(t, buildEnv = {}, runEnv = {}, flags = [], summary = {}):
        add(AllocsTest(t, buildEnv = buildEnv, runEnv = runEnv,
                       flags = flags, summary = summary))
        add(StockAllocsTest(t, buildEnv = buildEnv, runEnv = runEnv,
                            flags = flags, summary = summary))

    def addCrunchTest(t, buildEnv = {}, runEnv = {},
                      fail = False, flags = [], summary = {}):
        add(CrunchTest(t, buildEnv = buildEnv, runEnv = runEnv,
                       fail = fail, flags = flags, summary = summary))
        add(StockCrunchTest(t, buildEnv = buildEnv, runEnv = runEnv,
                            fail = fail, flags = flags, summary = summary))

    addAllocsTest("allocs/alloca.c", summary = {"a.stack": 1})

    multiAllocEnv = {"LIBALLOCS_ALLOC_FNS":
                        "xmalloc(Z)p xcalloc(zZ)p xrealloc(pZ)p",
                     "LIBALLOCS_SUBALLOC_FNS":
                        "g_slice_alloc(Z)p g_slice_alloc0(Z)p"}
    addAllocsTest("allocs/multi_alloc.c", summary = {},
                  flags = ["-Wl,--no-as-needed"] +
                          pkg_config("glib-2.0") +
                          ["-Wl,--as-needed"],
                  buildEnv = multiAllocEnv, runEnv = multiAllocEnv)

    addAllocsTest("allocs/offsetof_composite.c", summary = {"a.heap": 1})
    addAllocsTest("allocs/offsetof_simple.c", summary = {"a.heap": 1})
    addAllocsTest("allocs/simple.c", summary = {"a.heap": 1})
    addAllocsTest("allocs/sloppy_dumptypes.c", summary = {})
    addAllocsTest("allocs/uniqtype_walk.c", flags = ["-lallocs"],
                  summary = {"a.heap": 1})
    #addAllocsTest("allocs/sizefunc_arith.c", summary = {"a.heap": 2})
    addAllocsTest("allocs/sizefunc_iterate.c", summary = {"a.heap": 2})
    addAllocsTest("allocs/sizefunc_indirect.c", summary = {"a.heap": 2})
    addAllocsTest("allocs/arith.c", summary = {"a.heap": 2})
    addAllocsTest("allocs/reuse.c", summary = {"a.heap": 2})
    #addAllocsTest("allocs/reuse_global.c", summary = {"a.heap": 2})
    addAllocsTest("allocs/relf_auxv_dynamic.c", flags = ["-ldl"])

    summ = {"c.begun": 1, "c.remaining": 1, "c.nontriv": 1, "a.heap": 1}
    add(CrunchMakefileTest("crunch/section_group", summary = summ))
    add(StockCrunchMakefileTest("crunch/section_group", summary = summ))

    summary = {"c.begun": 1, "c.remaining": 1, "c.nontriv": 1, "a.heap": 1}
    add(CrunchMakefileTest("crunch/incomplete", summary = summ))
    add(StockCrunchMakefileTest("crunch/incomplete", summary = summ))

    addCrunchTest("crunch/array.c",
                  summary = {"c.begun": 2, "c.remaining": 2, "c.nontriv": 2,
                             "a.static": 2})

    addCrunchTest("crunch/function_refines.c",
                  summary = {"c.remaining": 1, "c.nontriv": 1, "a.static": 1,
                             "c.begun": 1})

    addCrunchTest("crunch/heap.c",
                  summary = {"a.heap": 1, "c.nontriv": 2, "c.remaining": 2,
                             "c.hit_cache": 1, "c.begun": 2})

    addCrunchTest("crunch/indirect.c", flags = ["-O0"],
                  summary = {"c.begun": 10, "c.nontriv": 10, "a.heap": 5,
                             "c.hit_cache": 5, "c.remaining": 10})

    addCrunchTest("crunch/qualified_char.c", summary = {})

    addCrunchTest("crunch/fail/funptr.c", fail = True,
                  summary = {"c.remaining": 1, "a.static": 1, "c.begun": 1,
                             "c.failed_other": 1})

    addCrunchTest("crunch/fail/va_arg.c", fail = True,
                  summary = {"c.begun": 3, "a.stack": 3, "c.remaining": 3,
                             "c.failed_other": 3})

    addCrunchTest("crunch/fail/voidptrptr_invalid.c", fail = True,
                  summary = {"a.stack": 4, "c.begun": 4,
                             "c.remaining": 4, "c.failed_other": 4})

    addCrunchTest("crunch/fail/voidptrptr_strict.c", fail = True,
                  buildEnv = {"LIBCRUNCH_STRICT_GENERIC_POINTERS": "1"},
                  summary = {"c.begun": 2, "a.stack": 2, "c.remaining": 2,
                             "c.failed_other": 2})

    addCrunchTest("crunch/funptr.c",
                  buildEnv = {"LIBCRUNCH_SLOPPY_FUNCTION_POINTERS": "1"},
                  summary = {"c.begun": 3, "c.remaining": 2, "c.nontriv": 2,
                  "a.static": 2, "a.abort_storage": 1, "a.stack": 1,
                  "c.hit_cache": 1})

    addCrunchTest("crunch/hello.c")

    addCrunchTest("crunch/hello_errno.c")

    addCrunchTest("crunch/lazy_typing.c",
                  buildEnv = {"LIBCRUNCH_LAZY_HEAP_TYPES": "__PTR_void sockaddr"},
                  runEnv = {"LIBCRUNCH_LAZY_HEAP_TYPES": "__PTR_void sockaddr"},
                  summary = {"c.begun": 2, "c.remaining": 2,
                             "c.lazy_heap": 2, "a.heap": 2})

    addCrunchTest("crunch/like_a.c",
                  buildEnv = {"LIBCRUNCH_USE_LIKE_A_FOR_TYPES": "sockaddr",
                              "LIBCRUNCH_LAZY_HEAP_TYPES": "sockaddr"},
                  runEnv = {"LIBCRUNCH_LAZY_HEAP_TYPES": "sockaddr"},
                  summary = {"c.begun": 2, "c.remaining": 2, "c.lazy_heap": 1,
                             "c.nontriv": 1, "a.heap": 2})

    addCrunchTest("crunch/nullcheck.c")

    addCrunchTest("crunch/random.c",
                  summary = {"c.begun": 1003, "a.heap": 339,
                             "c.remaining": 1003, "c.failed_other": 334,
                             "c.nontriv": 669, "c.hit_cache": 997})

    addCrunchTest("crunch/sizeofness.c",
                  summary = {"c.begun": 2, "c.remaining": 2, "c.hit_cache": 1,
                             "a.heap": 1, "c.nontriv": 2})

    addCrunchTest("crunch/stack.c",
                  summary = {"c.begun": 2, "a.stack": 2, "c.nontriv": 2,
                             "c.remaining": 2})

    addCrunchTest("crunch/stackactual.c",
                  summary = {"c.begun": 1, "a.stack": 1, "c.nontriv": 1,
                             "c.remaining": 1})

    addCrunchTest("crunch/static.c",
                  summary = {"c.begun": 1, "c.remaining": 1, "c.nontriv": 1,
                             "a.static": 1})

    addCrunchTest("crunch/stubgen.c",
                  buildEnv = {"LIBALLOCS_ALLOC_FNS": "xmalloc(Z)p"},
                              flags = ["-Wl,--defsym,xmalloc=__my_xmalloc",
                                       "-O0"],
                  summary = {"c.begun": 2, "a.heap": 1, "c.nontriv": 2,
                             "c.hit_cache": 1, "c.remaining": 2})

    addCrunchTest("crunch/union.c",
                  summary = {"c.begun": 5, "c.remaining": 5, "c.nontriv": 5,
                             "a.static": 5})

    addCrunchTest("crunch/va_arg.c",
                  summary = {"c.begun": 3, "c.remaining": 3, "a.stack": 3,
                             "c.nontriv": 3})

    addCrunchTest("crunch/void.c",
                  summary = {"c.begun": 1, "c.remaining": 1, "c.nontriv": 1,
                             "a.heap": 1})

    addCrunchTest("crunch/voidptrptr.c",
                  summary = {"c.begun": 2, "c.remaining": 2, "c.nontriv": 2,
                             "a.stack": 4})

    addCrunchTest("broken/pointer_degree.c", fail = True,
                  summary = {"a.stack": 17})

    return tests

def zshcomp(tests, prefix = ""):
    tests = list(tests) + ["ALL", "ALLclang", "CLEAN"]
    tests.sort()
    for t in tests:
        print(prefix, t)
    # HACK: To enable complete for the -rNUM option, just add them here.
    print("-r1\n-r2\n-r3\n-r4\n-r5\n-r10")

def helpAndExit(tests):
    print("Usage: %s TEST ..." % sys.argv[0])
    print("Available tests:")
    zshcomp(tests, prefix = "   ")
    sys.exit(0)

def parseArgs(allTests):
    argv = sys.argv[1:]
    ret = set()
    numRepeats = 1

    if len(argv) == 0:
        helpAndExit(allTests)
        return [ret, 0]

    if "ALL" in argv:
        for tn in allTests:
            if not tn.startswith("broken/"):
                ret.add(tn)
        argv.remove("ALL")

    if "ALLclang" in argv:
        for tn in allTests:
            if not tn.startswith("broken/") and not tn.startswith("stock/"):
                ret.add(tn)
        argv.remove("ALLclang")

    # For each argument, add every test that is a prefix match of that
    # argument.
    for arg in argv:
        if arg.startswith("-r"):
            numRepeats = int(arg[2:])
            continue

        numMatched = 0
        for tn in allTests:
            if tn.startswith(arg):
                ret.add(tn)
                numMatched += 1
        if numMatched == 0:
            print("Error: No tests match '%s'." % arg)
            return [{}, 0]
    return [ret, numRepeats]

def boxMessage(msg):
    assert type(msg) == str

    width = len(msg) + 2
    print("+" + width * "-" + "+")
    print("| " + msg + " |")
    print("+" + width * "-" + "+")

class Timings:
    def __init__(self):
        self.stockTimes = {}
        self.newTimes = {}
        self.allNames = set()

    def add(self, name, time):
        if name.startswith("stock/"):
            addTo = self.stockTimes
            name = name[6:]
        else:
            addTo = self.newTimes

        if name not in addTo:
            addTo[name] = []
        addTo[name].append(time)
        self.allNames.add(name)

    def writeSingle(self, fp, tn, xpos):
        stockMean = None
        newMean = None

        if tn in self.stockTimes:
            stockMean = numpy.mean(self.stockTimes[tn])
        if tn in self.newTimes:
            newMean = numpy.mean(self.newTimes[tn])

        if tn in self.stockTimes and tn in self.newTimes:
            stk = self.stockTimes[tn]
            new = self.newTimes[tn]
            fp.write("\\texttt{" + tn.replace("_", "\\_") + "}\t")
            fp.write(str(xpos) + "\t")
            fp.write(str(numpy.mean(stk)) + "\t" + str(numpy.std(stk)) + "\t")
            fp.write(str(numpy.mean(new)) + "\t" + str(numpy.std(new)) + "\n")

    def write(self, fname):
        with open(fname, "w") as fp:
            fp.write("TestName\tXPos\tStockMean\tStockSTD\tNewMean\tNewSTD\n")
            allNames = list(self.allNames)
            allNames.sort()
            xpos = 0
            for tn in allNames:
                self.writeSingle(fp, tn, xpos)
                xpos += 1

def runTestList(tests, testsToRun, buildTimes, runTimes):
    nonexist = 0
    passed = 0
    cancelled = 0
    failed_build = []
    failed_returncode = []
    failed_summary = []
    total = len(testsToRun)

    try:
        for tn in testsToRun:
            if tn not in tests:
                print("Error: No such test: \'" + tn + "\'")
                nonexist += 1
                continue
            T = tests[tn]
            if T.build() != 0:
                failed_build += [tn]
                continue
            if T.run() != 0:
                failed_returncode += [tn]
                continue
            if not T.checkSummary():
                failed_summary += [tn]
                continue
            boxMessage("Passed test '" + tn + "'")
            print("\n")

            buildTimes.add(tn, T.buildTime)
            runTimes.add(tn, T.runTime)

            passed += 1
    except KeyboardInterrupt:
        cancelled = total - passed \
                  - len(failed_build) \
                  - len(failed_returncode) \
                  - len(failed_summary)
        pass

    failed_build.sort()
    failed_returncode.sort()
    failed_summary.sort()

    print()
    print("Summary:")
    print("    Passed              :", passed)
    print("    Failed (build)      :", len(failed_build),
          " ".join(failed_build))
    print("    Failed (returncode) :", len(failed_returncode),
          " ".join(failed_returncode))
    print("    Failed (summary)    :", len(failed_summary),
          " ".join(failed_summary))
    print("    Invalid             :", nonexist)
    print("    Cancelled           :", cancelled)
    print("    Total               :", total)

def main():
    tests = register_tests()

    if "ZSHCOMP" in sys.argv:
        zshcomp(tests)
        sys.exit(0)

    if "CLEAN" in sys.argv:
        for t in tests:
            tests[t].clean()
        def cleanDir(directory):
            for f in os.listdir(directory):
                fullpath = path.join(directory, f)
                if path.isdir(fullpath):
                    cleanDir(fullpath)
                    continue
                for e in CLEAN_EXTS:
                    if fullpath.endswith(e) and path.exists(fullpath):
                        os.unlink(fullpath)
        cleanDir(TESTDIR)
        return 0

    [testsToRun, numRepeats] = parseArgs(tests)

    if len(testsToRun) == 0 or numRepeats == 0:
        return

    buildTimes = Timings()
    runTimes = Timings()

    # Combine all repeats into one huge list, then shuffle it
    testsToRun = numRepeats * list(testsToRun)
    random.shuffle(testsToRun)

    runTestList(tests, testsToRun, buildTimes, runTimes)

    buildTimes.write(path.join(TESTDIR, "buildTimes.dat"))
    runTimes.write(path.join(TESTDIR, "runTimes.dat"))


if __name__ == "__main__":
    main()
