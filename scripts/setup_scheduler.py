"""Create a Windows Task Scheduler task that runs `python run.py --if-due`
three times a day: 00:30, 12:00, and 18:00 (local time).

`--if-due` gates each run on a timestamp file, so if the laptop was asleep
across one or more scheduled times, only ONE catch-up scrape runs on wake-up
instead of one per missed slot.

Run this script once (no admin needed for a per-user task):

    python scripts/setup_scheduler.py

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
PYTHON = sys.executable
SCRIPT = os.path.join(ROOT, "run.py")

# One daily CalendarTrigger per slot. XML is used (rather than the schtasks
# CLI flags) because only XML exposes StartWhenAvailable and
# MultipleInstancesPolicy.
TRIGGER_TEMPLATE = """\
    <CalendarTrigger>
      <StartBoundary>{date}T{time}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>"""

TASK_XML = """\
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Scrapes career pages 3x/day (00:30, 12:00, 18:00). Missed runs collapse into one catch-up.</Description>
  </RegistrationInfo>
  <Triggers>
{triggers}
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
  </Settings>
  <Actions>
    <Exec>
      <Command>{python}</Command>
      <Arguments>"{script}" --if-due</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def main():
    triggers = "\n".join(
        TRIGGER_TEMPLATE.format(date=START_DATE, time=t) for t in SLOTS
    )
    xml = TASK_XML.format(
        triggers=triggers,
        python=PYTHON,
        script=SCRIPT,
        workdir=ROOT,
    )

    # Write XML to a temp file so schtasks can read it.
    xml_path = os.path.join(tempfile.gettempdir(), "jobscraper_task.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml)

    cmd = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/XML", xml_path,
        "/F",  # overwrite if exists
    ]

    print(f"Creating scheduled task '{TASK_NAME}'...")
    print(f"  Runs daily at:       {', '.join(SLOTS)}")
    print(f"  Run on wake-up:      yes (catches up a missed slot)")
    print(f"  Missed-run dedupe:   yes (--if-due collapses a backlog into one run)")
    print(f"  Stack instances:     no (IgnoreNew — only one at a time)")
    print(f"  Needs network:       yes (skips if offline)")
    print(f"  Working directory:   {ROOT}")
    print()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("Task created successfully.")
            print(f"To verify:  schtasks /Query /TN \"{TASK_NAME}\" /V /FO LIST")
            print(f"To delete:  schtasks /Delete /TN \"{TASK_NAME}\" /F")
            print(f"To run now: schtasks /Run /TN \"{TASK_NAME}\"")
        else:
            print(f"Failed (exit {result.returncode}):")
            print(result.stderr or result.stdout)
            if "Access is denied" in (result.stderr or ""):
                print("\nTry running this script as Administrator.")
    except FileNotFoundError:
        print("schtasks not found — this script only works on Windows.")
        print("On Linux/macOS, add these to your crontab instead:")
        for t in SLOTS:
            hh, mm = t.split(":")
            print(f"  {int(mm)} {int(hh)} * * *  cd {ROOT} && {PYTHON} run.py --if-due >> scrape.log 2>&1")
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
