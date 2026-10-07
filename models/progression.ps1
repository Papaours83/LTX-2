$host.UI.RawUI.WindowTitle = "Telechargement LTX-2.5"
$dir = "C:\Users\hugoc\Desktop\git\LTX-2\models\ltx-2.5"
$fichiers = @{
    "diffusion_models\ltx-2.5-22b-distilled-transformer-bf16.safetensors"             = @{ taille = 42018190584; id = "M5jL446tNjQy" }
    "text_encoders\gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"                     = @{ taille = 26263858182; id = "XkM862jhi1Hg" }
    "vae\ltx-2.5-video-vae-conv-bf16.safetensors"                                     = @{ taille = 1452269922;  id = "20r0yAT48ROz" }
    "vae\ltx-2.5-audio-vae-bf16.safetensors"                                          = @{ taille = 364866540;   id = "tbsTpTFYGH54" }
    "latent_upscale_models\ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"   = @{ taille = 995778752;   id = "zt77RIREUEn2" }
}
$total = ($fichiers.Values | ForEach-Object { $_.taille } | Measure-Object -Sum).Sum

# Windows ne met pas a jour la taille affichee d'un fichier en cours d'ecriture :
# on ouvre chaque fichier pour lire sa vraie taille.
function Taille-Reelle($chemin) {
    try { $fs = [IO.File]::Open($chemin, 'Open', 'Read', 'ReadWrite,Delete'); $l = $fs.Length; $fs.Close(); $l } catch { 0 }
}

function Telecharge {
    $s = 0
    foreach ($nom in $fichiers.Keys) {
        $f = $fichiers[$nom]
        if (Test-Path "$dir\$nom") { $s += $f.taille; continue }
        $partiels = Get-ChildItem "$dir\.cache" -Recurse -File -Force -Filter "$($f.id)*.incomplete" -ErrorAction SilentlyContinue
        $s += ($partiels | ForEach-Object { Taille-Reelle $_.FullName } | Measure-Object -Maximum).Maximum
    }
    $s
}

$last = Telecharge; $lastT = Get-Date
while ($true) {
    Start-Sleep 3
    $s = Telecharge
    $now = Get-Date
    $speed = [math]::Max(0, ($s - $last) / ($now - $lastT).TotalSeconds / 1MB)
    $last = $s; $lastT = $now
    $pct = [math]::Min(100, [math]::Round($s / $total * 100, 1))
    $restant = if ($speed -gt 0.1) { "{0:N0} min" -f (($total - $s) / 1MB / $speed / 60) } else { "..." }
    Write-Progress -Activity "Telechargement des modeles LTX-2.5" `
        -Status ("{0} %  -  {1:N1} / {2:N1} Go  -  {3:N0} Mo/s  -  reste environ {4}" -f $pct, ($s/1GB), ($total/1GB), $speed, $restant) `
        -PercentComplete $pct
    if (-not (Get-Process hf -ErrorAction SilentlyContinue)) {
        Write-Progress -Activity "Telechargement" -Completed
        Write-Host "`nTelechargement termine ! Tu peux fermer cette fenetre." -ForegroundColor Green
        break
    }
}
Read-Host "Appuie sur Entree pour fermer"
