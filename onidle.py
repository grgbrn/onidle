#!/usr/bin/env python3

#
# attempt to determine if a machine is idle and therefore it's a good time
# to run maintainence tasks like backups
#
# things to check:
# - time since last wakeup
# - current system load
# - is user idle? (terminal, or on x11/wayland)
# - connected to a known wifi network (laptop)
# - not on battery power and have sufficient charge level (laptop)

# if it runs as a daemon or something it can record observations of
# times that tend to be idle and it can use them? like the time you
# typically take a lunch break or go to a meeting?

import datetime
import functools
import subprocess
import time

# probes should be trinary?
# True means system is idle
# False means system is not idle
# None means this probe can't decide
# (and throw an exception if things are really wrong)

##
##  probes
##


def systemd_wake():
    # journalctl -n4 -u sleep.target
    # journalctl -t systemd-sleep
    # needs to take into account reboots if no wake is found
    last_wake_line = None

    r = subprocess.run(
        ["journalctl", "-t", "systemd-sleep"],
        capture_output=True,
        encoding="utf8",
        check=True,
    )
    for line in lines(r.stdout):
        if line.endswith("System returned from sleep state."):
            last_wake_line = line

    if not last_wake_line:
        return None

    now = datetime.datetime.now()

    # Feb 07 09:48:59 fedora systemd-sleep[129721]: System returned from sleep state.
    tmp = line[:15]
    dt = datetime.datetime.strptime(tmp, "%b %d %H:%M:%S")
    dt = dt.replace(year=now.year)  # XXX

    ago = now - dt
    print(f"last wake was {ago} ago (at {dt})")

    # heuristic: 10 minutes since last wake
    return ago.total_seconds() >= 60 * 10


def proc_uptime():
    # /proc/uptime
    # https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/6/html/deployment_guide/s2-proc-uptime
    # first number is total seconds the system has been up
    with open("/proc/uptime", "r") as f:
        dat = lines(f.read())
        assert len(dat) == 1
        line = dat[0]
        total_seconds = float(line.split()[0])
        total_minutes = int(total_seconds / 60)

        print(f"system uptime is {total_minutes} minutes ({total_seconds} sec)")

        # heuristic: 10 minutes since last reboot
        return total_minutes > 10


def proc_loadavg():
    # /proc/loadavg
    # https://stackoverflow.com/questions/11987495/what-do-the-numbers-in-proc-loadavg-mean-on-linux
    # https://www.brendangregg.com/blog/2017-08-08/linux-load-averages.html

    cpu_count = get_cpu_count()

    with open("/proc/loadavg", "r") as f:
        dat = lines(f.read())
        assert len(dat) == 1
        values = dat[0].split()

        current_load = float(values[0])

        # XXX can we use this?
        # tmp = values[3].split("/")
        # executing_count = int(tmp[0])

        half_cpu_count = int(cpu_count / 2)
        print(
            f"system load: {current_load} cpu count:{cpu_count} (threshold:{half_cpu_count})"
        )

        # heuristic: load is less than half cpu/core count
        return current_load < half_cpu_count


def idle_terminal():
    # who -u -H
    r = subprocess.run(["who", "-u"], capture_output=True, encoding="utf8", check=True)

    def parse(s):
        "return number of minutes of inactivity from string value"
        if s == ".":
            return 0

        if ":" not in s:
            return None

        tmp = s.split(":")
        assert len(tmp) == 2
        return int(tmp[0]) * 60 + int(tmp[1])

    idle_times = []
    for line in lines(r.stdout):
        # greg     pts/2        2023-02-06 15:17   .         59698 (:0)
        # greg     pts/3        2023-02-06 15:56 20:13       65114 (:0)
        fields = line.split()
        idle_times.append(fields[4])

    # i am the walrus koo koo cachoo
    tmp = [val for x in idle_times if (val := parse(x)) is not None]

    idle_minutes = min(tmp)
    print(f"terminal idle for {idle_minutes} min")

    # heuristic: terminal session has been idle for at least 5 minutes
    # XXX: probably want to make this longer
    return idle_minutes >= 5


def xprintidle():
    # https://github.com/g0hl1n/xprintidle
    r = subprocess.run(["xprintidle"], capture_output=True, encoding="utf8", check=True)

    dat = lines(r.stdout)
    assert len(dat) == 1
    idle_ms = int(dat[0])

    print(f"X11 idle for {idle_ms/1000} seconds")

    # heuristic: x11 session has been idle for 5 minutes
    # XXX probably want to make this longer?
    return idle_ms >= 5 * 60 * 1000


def idle_wayland():
    # TODO
    pass


def idle_osx():
    # TODO
    pass


##
##  probe helper functions
##


def lines(stdout):
    "split process output into a list of lines"
    return stdout.strip().split("\n")


@functools.cache  # aka memoize
def get_cpu_count():
    "returns number of cpu cores on this system"
    # https://unix.stackexchange.com/questions/218074/how-to-know-number-of-cores-of-a-system-in-linux
    r = subprocess.run(
        ["nproc", "--all"], capture_output=True, encoding="utf8", check=True
    )
    dat = lines(r.stdout)
    assert len(dat) == 1
    return int(dat[0])


@functools.cache
def which(binary_name):
    "return the full path of binary_name, or None if it is not present"
    r = subprocess.run(["which", binary_name], capture_output=True, encoding="utf8")
    if r.returncode != 0:
        return None

    dat = lines(r.stdout)
    assert len(dat) == 1
    return dat[0]


def init_probes():
    "select probes that make sense for this system"
    # TODO: platform, laptop vs. desktop, etc
    probes = [systemd_wake, proc_uptime, proc_loadavg, idle_terminal]

    # XXX should also probe that the system uses X11
    # XXX doesn't make sense to also use idle_terminal if xprintidle works
    xprintidle_path = which("xprintidle")
    if xprintidle_path:
        print(f"found {xprintidle_path}")
        probes.append(xprintidle)

    return probes


def test(probes, verbose=False):
    "run continuously and print idle status to terminal"
    while True:
        now = datetime.datetime.now()
        print(f">>> idle probe at {now}")

        results = []
        for probe in probes:
            print(f"running probe {probe}")
            r = probe()
            print(f"probe result: {r}")
            results.append(r)

        final = all(x != False for x in results)
        print(f"final result: {final} (from {len(results)} probes)\n")

        time.sleep(60)


def main():
    all_probes = init_probes()
    print(f"using probes: {all_probes}\n")

    # this should be a flag, normal mode of operation should
    # be to wait until all idle probes return true and then
    # execute the shell comamnd and exit
    test(all_probes, verbose=True)


if __name__ == "__main__":
    main()
