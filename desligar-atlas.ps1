# Desliga o Atlas por completo: o servidor (pythonw), o reconhecedor de voz na GPU e a janela dele no Edge.
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'servidor\.py' -or $_.CommandLine -match 'atlas\\\.perfil-edge' -or $_.Name -eq 'whisper-server.exe' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
