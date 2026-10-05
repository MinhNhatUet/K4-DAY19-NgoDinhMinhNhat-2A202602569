from pathlib import Path
import re, subprocess
from dotenv import dotenv_values
secrets = [v for k,v in dotenv_values('.env').items() if ('KEY' in k or 'SECRET' in k or 'PASSWORD' in k) and v and len(v)>12]
paths = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard'],text=True).splitlines()
hits=[]
for name in paths:
    p=Path(name)
    if p.suffix.lower() in {'.png','.jpg','.pyc'}: continue
    data=p.read_text(encoding='utf-8-sig',errors='replace')
    if any(s in data for s in secrets) or re.search(r'sk-(?:proj-)?[A-Za-z0-9_-]{20,}',data): hits.append(name)
history=subprocess.check_output(['git','log','--all','-p'],encoding='utf-8',errors='replace')
print('Working-tree files with possible secrets:',hits)
print('History contains key pattern:',bool(re.search(r'sk-(?:proj-)?[A-Za-z0-9_-]{20,}',history)))
print('Tracked .env:', subprocess.check_output(['git','ls-files','.env'],text=True).strip() or 'none')
