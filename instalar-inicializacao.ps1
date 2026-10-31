# Cria atalhos do Atlas na Area de Trabalho e na Inicializacao do Windows.
$pasta = Split-Path -Parent $MyInvocation.MyCommand.Path
$sh = New-Object -ComObject WScript.Shell
foreach ($destino in @([Environment]::GetFolderPath('Startup'), [Environment]::GetFolderPath('Desktop'))) {
    $lnk = $sh.CreateShortcut((Join-Path $destino 'Atlas.lnk'))
    $lnk.TargetPath = 'wscript.exe'
    $lnk.Arguments = '"' + (Join-Path $pasta 'iniciar-atlas.vbs') + '"'
    $lnk.WorkingDirectory = $pasta
    $lnk.Save()
}
Write-Host 'Atlas vai iniciar junto com o Windows. Atalho criado na Area de Trabalho.'
