# Reinicia Ollama + Atlas do zero (use se algo travar).
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $pasta 'desligar-atlas.ps1')
Get-Process | Where-Object { $_.Name -match '^ollama' -or $_.Name -eq 'llama-server' } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep 3
Start-Process "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
Start-Sleep 5
Start-Process wscript.exe -ArgumentList ('"' + (Join-Path $pasta 'iniciar-atlas.vbs') + '"')
Write-Host 'Ollama e Atlas reiniciados.'
