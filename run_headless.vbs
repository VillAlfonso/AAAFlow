' AAAFlow Studio - headless launcher (no console window).
' Runs the web server hidden, logs to data\server.log, opens the browser.
Set sh = CreateObject("WScript.Shell")
base = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
sh.CurrentDirectory = base
sh.Environment("PROCESS")("HF_HOME") = base & "models"
' window style 0 = hidden; logs go to data\server.log
sh.Run "cmd /c """".venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > data\server.log 2>&1""", 0, False
WScript.Sleep 5000
sh.Run "http://127.0.0.1:8000", 1, False
