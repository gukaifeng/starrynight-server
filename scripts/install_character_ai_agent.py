#!/usr/bin/env python3
"""Install an isolated per-user runtime; no Documents access from launchd.

macOS can suspend a launchd Python process while it requests access to Documents.
Keep source deployment, venv, credentials, state and logs in Application Support.
The development checkout and its original state remain intact as a backup.
"""
import json, os, plistlib, shutil, sqlite3, subprocess, sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
private=root/'.local/character-ai/settings.json'
if not private.exists():raise SystemExit('Run setup_character_ai.py first.')
runtime=Path.home()/'Library/Application Support/StarryNightServer/CharacterAI'
runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
label='com.starrynight.server.character-ai';domain='gui/'+str(os.getuid())
subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True)
code=runtime/'code/services/character_ai';code.mkdir(parents=True,exist_ok=True)
for source in (root/'services/character_ai').glob('*.py'):shutil.copy2(source,code/source.name)
shutil.copy2(root/'services/character_ai/performance_catalog.json',code/'performance_catalog.json')
shutil.copy2(root/'services/character_ai/opening_catalog.json',code/'opening_catalog.json')
shutil.copy2(root/'services/character_ai/character_profiles.json',code/'character_profiles.json')
shutil.copy2(root/'services/character_ai/character_scenarios.json',code/'character_scenarios.json')
shutil.copy2(root/'services/character_ai/novelty-model.lock.json',code/'novelty-model.lock.json')
venv=runtime/'.venv';python=venv/'bin/python'
if not python.exists():subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
with (runtime/'dependency-install.log').open('w') as log:
    subprocess.run([str(python),'-m','pip','install','-r',str(root/'services/character_ai/requirements.lock')],stdout=log,stderr=subprocess.STDOUT,check=True)
config=json.loads(private.read_text());old_data=Path(config.get('data_dir',root/'.local/character-ai'))
data=runtime/'data';data.mkdir(exist_ok=True,mode=0o700)
if old_data!=data and not (data/'state.sqlite3').exists():
    if (old_data/'state.sqlite3').exists():
        source=sqlite3.connect(old_data/'state.sqlite3');dest=sqlite3.connect(data/'state.sqlite3')
        source.backup(dest);source.close();dest.close()
    for name in ['voices','audio']:
        if (old_data/name).exists():shutil.copytree(old_data/name,data/name,dirs_exist_ok=True)
config['data_dir']=str(data)
settings=runtime/'settings.json';settings.write_text(json.dumps(config,indent=2));settings.chmod(0o600)
# CLI maintenance and the running daemon must consult the same budget/history.
private.write_text(json.dumps(config,indent=2));private.chmod(0o600)
logs=runtime/'logs';logs.mkdir(exist_ok=True,mode=0o700)
folder=Path.home()/'Library/LaunchAgents';folder.mkdir(exist_ok=True)
path=folder/(label+'.plist')
value={'Label':label,'ProgramArguments':[str(python),'-m','uvicorn','services.character_ai.app:create_app','--factory','--host','127.0.0.1','--port','18766','--no-access-log','--log-level','warning'],
       'WorkingDirectory':str(runtime/'code'),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,
       'EnvironmentVariables':{'PYTHONPATH':str(runtime/'code'),'STARRY_AI_CONFIG':str(settings),'PYTHONUNBUFFERED':'1'},
       'StandardOutPath':str(logs/'gateway.log'),'StandardErrorPath':str(logs/'gateway-error.log')}
path.write_bytes(plistlib.dumps(value));path.chmod(0o600)
subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True)
print('Local AI gateway deployed to Application Support on port 18766. No provider call made.')
