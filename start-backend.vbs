Set oShell = CreateObject("WScript.Shell")
oShell.Run "cmd /c cd /d C:\Users\lenovo\Documents\MYAPPS\FMS && python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002 >> C:\Users\lenovo\Documents\MYAPPS\FMS\backend.log 2>&1", 0, False
