# 用官方 COM 读回 .lnk 的真实内容（作为判定真相的依据）
param([string]$Folder)
$sh = New-Object -ComObject WScript.Shell
Get-ChildItem "$Folder\*.lnk" | Sort-Object Name | ForEach-Object {
    $s = $sh.CreateShortcut($_.FullName)
    '{0}|target={1}|args={2}|desc={3}|wd={4}|icon={5}' -f `
        $_.Name, $s.TargetPath, $s.Arguments, $s.Description, $s.WorkingDirectory, $s.IconLocation
}
