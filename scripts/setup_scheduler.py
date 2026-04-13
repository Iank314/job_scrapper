"""Create a Windows Task Scheduler task that runs `python run.py --scrape`
every 8 hours. If the computer was off, it runs once on wake-up (not once
per missed interval).

Run this script once with admin privileges:

    python scripts/setup_scheduler.py

To remove the task later:
    schtasks /Delete /TN "JobScraper" /F
"""

import os
import subprocess
import sys
import tempfile

TASK_NAME = "JobScraper"
INTERVAL_HOURS = 24
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
SCRIPT = os.path.join(ROOT, "run.py")
LOG_FILE = os.path.join(ROOT, "scrape.log")

# XML task definition — this is the only way to set StartWhenAvailable
# and MultipleInstancesPolicy, which schtasks CLI doesn't expose.
TASK_XML = """\
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{hours}H</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-04-12T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
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
      <Arguments>"{script}" --scrape</Arguments>
      <WorkingDirectory>{workdir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def main():
    xml = TASK_XML.format(
        hours=INTERVAL_HOURS,
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
    print(f"  Interval:            every {INTERVAL_HOURS} hours")
    print(f"  Run on wake-up:      yes (catches up missed runs)")
    print(f"  Stack missed runs:   no (IgnoreNew — only one instance at a time)")
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
        print("On Linux/macOS, add this to your crontab instead:")
        minutes = INTERVAL_HOURS * 60
        print(f"  0 */{INTERVAL_HOURS} * * * cd {ROOT} && {PYTHON} run.py --scrape >> scrape.log 2>&1")
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
