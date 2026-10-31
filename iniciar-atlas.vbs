' Liga o Atlas sem janela preta e abre a interface como um app.
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
pasta = fs.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = pasta

' Garante que o Ollama esta rodando
sh.Run """" & sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Ollama\ollama app.exe""", 0, False

' Reconhecedor de voz na placa de video AMD (whisper.cpp + Vulkan), se estiver compilado
exe = fs.GetParentFolderName(pasta) & "\motores\whisper.cpp\build\bin\whisper-server.exe"
If fs.FileExists(exe) Then
  sh.Run """" & exe & """ -m """ & pasta & "\modelos-voz\ggml-large-v3-turbo-q8_0.bin"" -l pt --host 127.0.0.1 --port 7778 -t 4 -fa --suppress-nst -nth 0.6 --vad -vm """ & pasta & "\modelos-voz\ggml-silero-v5.1.2.bin"" -vt 0.55", 0, False
End If

' Liga o servidor do Atlas (se ja estiver ligado, o segundo apenas encerra)
sh.Run """" & pasta & "\.venv\Scripts\pythonw.exe"" """ & pasta & "\servidor.py""", 0, False

' Espera o servidor responder (ate ~60s, o modelo de voz demora na 1a vez)
Set http = CreateObject("MSXML2.XMLHTTP")
For i = 1 To 60
  On Error Resume Next
  http.Open "GET", "http://127.0.0.1:7777/config", False
  http.Send
  If Err.Number = 0 And http.Status = 200 Then Exit For
  Err.Clear
  On Error GoTo 0
  WScript.Sleep 1000
Next

' Perfil proprio do Atlas, com microfone e camera liberados para ele
perfil = pasta & "\.perfil-edge"
sh.Run "msedge --app=http://127.0.0.1:7777 --window-size=1400,850 --user-data-dir=""" & perfil & """ --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required", 1, False
