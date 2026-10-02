"""One versioned location for thresholds, evidence weights and time policy."""
import json
from pathlib import Path
from datetime import datetime, timezone
POLICY=json.loads(Path(__file__).with_name('learning_policy.json').read_text())
TYPES=set(POLICY['weights'])
SOURCES={'lesson','quiz','assessment','review','ai_tutor','remediation','system'}
DIMENSION={'concept':'understanding','application':'application','math':'application','reasoning':'application','transfer':'transfer'}

def clock():return datetime.now(timezone.utc)
def iso(at):return at.astimezone(timezone.utc).isoformat(timespec='seconds')
def date(value):return (datetime.fromisoformat(value).replace(tzinfo=timezone.utc) if datetime.fromisoformat(value).tzinfo is None else datetime.fromisoformat(value).astimezone(timezone.utc)) if value else None
