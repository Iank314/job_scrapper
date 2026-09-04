"""Create a Windows Task Scheduler task that runs `python run.py --if-due`
three times a day: 00:30, 12:00, and 18:00 (local time).

`--if-due` gates each run on a timestamp file, so if the laptop was asleep
across one or more scheduled times, only ONE catch-up scrape runs on wake-up
instead of one per missed slot.

Run this script once (no admin needed for a per-user task):

    venv\\Scripts\\python.exe scripts/setup_scheduler.py

To remove the task later:
    schtasks /Delete /TN "JobScraper" /F
"""

import os
import subprocess
import sys
import tempfile

TASK_NAME = "JobScraper"
# Daily run times (24h). Keep in sync with SCHEDULE_SLOTS in schedule_gate.py.
SLOTS = ["00:30", "12:00", "18:00"]
# Any past date works; only the time-of-day drives the daily recurrence.
START_DATE = "2025-01-01"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "run.py")
LOG = os.path.join(ROOT, "scrape.log")

# Prefer the project venv over whatever interpreter launched this script — the
# scheduled task must use the one that actually has the dependencies installed.
_VENV_PYTHON = os.path.join(ROOT, "venv", "Scripts", "python.exe")
PYTHON = _VENV_PYTHON if os.path.exists(_VENV_PYTHON) else sys.executable

COMSPEC = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
USER = "{}\\{}".format(os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""))

# One daily CalendarTrigger per slot. XML is used (rather than the schtasks
# CLI flags) because only XML exposes StartWhenAvailable, WakeToRun,
# MultipleInstancesPolicy and the logon-type principal.
TRIGGER_TEMPLATE = """\
    <CalendarTrigger>
      <StartBoundary>{date}T{time}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>"""

# The action runs through cmd.exe purely to append stdout/stderr to scrape.log —
# an unattended 00:30 run is undebuggable otherwise. `>` and `&` are XML-escaped.
ACTION_ARGS = (
    '/c &quot;&quot;{python}&quot; &quot;{script}&quot; --if-due '
    '&gt;&gt; &quot;{log}&quot; 2&gt;&amp;1&quot;'
)

TASK_XML = """\
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Scrapes career pages 3x/day (00:30, 12:00, 18:00). Missed runs collapse into one catch-up.</Description>
  </RegistrationInfo>
  <Triggers>
{triggers}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>{logon_type}</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <RestartOnFailure>
      <Interval>PT30M</Interval>
      <Count>2</Count>
    </RestartOnFailure>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <Hidden>false</Hidden>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def build_xml(logon_type):
    triggers = "\n".join(
        TRIGGER_TEMPLATE.format(date=START_DATE, time=t) for t in SLOTS
    )
    return TASK_XML.format(
        triggers=triggers,
        user=USER,
        logon_type=logon_type,
        command=COMSPEC,
        arguments=ACTION_ARGS.format(python=PYTHON, script=SCRIPT, log=LOG),
        workdir=ROOT,
    )


def register(logon_type):
    """Try to register the task with the given logon type. Returns (ok, output)."""
    xml_path = os.path.join(tempfile.gettempdir(), "jobscraper_task.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(build_xml(logon_type))
    try:
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", xml_path, "/F"],
            capture_output=True, text=True,
        )
        return result.returncode == 0, (result.stderr or result.stdout).strip()
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass


def main():
    print(f"Creating scheduled task '{TASK_NAME}'...")
    print(f"  Runs daily at:       {', '.join(SLOTS)}")
    print(f"  Interpreter:         {PYTHON}")
    print(f"  Log file:            {LOG}")
    print(f"  Wake from sleep:     yes (WakeToRun)")
    print(f"  Run on wake-up:      yes (catches up a missed slot)")
    print(f"  Missed-run dedupe:   yes (--if-due collapses a backlog into one run)")
    print(f"  Stack instances:     no (IgnoreNew — only one at a time)")
    print(f"  Needs network:       yes (skips if offline, retries in 30m)")
    print(f"  Working directory:   {ROOT}")
    print()

    try:
        # S4U runs the task whether or not you're logged on, in a background
        # session with no console window. It needs the "log on as a batch job"
        # right, which a non-admin account may lack — fall back to the
        # logged-on-only mode rather than leaving no task at all.
        ok, output = register("S4U")
        if ok:
            print("Task created (runs whether or not you are logged on).")
        else:
            print(f"S4U registration failed, falling back to logged-on-only mode.")
            print(f"  reason: {output}")
            ok, output = register("InteractiveToken")
            if ok:
                print("Task created (runs only while you are logged on;")
                print("a brief console window will appear at each slot).")

        if ok:
            print()
            print(f"To verify:  schtasks /Query /TN \"{TASK_NAME}\" /V /FO LIST")
            print(f"To delete:  schtasks /Delete /TN \"{TASK_NAME}\" /F")
            print(f"To run now: schtasks /Run /TN \"{TASK_NAME}\"")
        else:
            print("Failed:")
            print(output)
            if "Access is denied" in output:
                print("\nTry running this script as Administrator.")
    except FileNotFoundError:
        print("schtasks not found — this script only works on Windows.")
        print("On Linux/macOS, add these to your crontab instead:")
        for t in SLOTS:
            hh, mm = t.split(":")
            print(f"  {int(mm)} {int(hh)} * * *  cd {ROOT} && {PYTHON} run.py --if-due >> scrape.log 2>&1")


if __name__ == "__main__":
    main()
