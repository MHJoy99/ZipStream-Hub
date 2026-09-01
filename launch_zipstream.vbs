' ==============================================================================
'  ZipStream Hub - Silent Background Launcher (No Console Window)
'  Runs control_panel.py in the background using pythonw without popups.
' ==============================================================================

Option Explicit

Dim WshShell, FSO, scriptDir, controlPanelPath

Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")

' Get root directory where this script is located
scriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
controlPanelPath = scriptDir & "\control_panel.py"

' Launch control_panel.py silently via pythonw with working directory set to scriptDir
WshShell.CurrentDirectory = scriptDir
WshShell.Run "pythonw """ & controlPanelPath & """", 0, False
