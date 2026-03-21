param(
    [string]$StackDir = "."
)

$ErrorActionPreference = "Stop"

Set-Location $StackDir

if (-not (Test-Path "env.example")) {
    throw "env.example not found. Run this script from cloud/aws."
}

if (-not (Test-Path ".env")) {
    Copy-Item "env.example" ".env"
    Write-Host "[deploy] Created .env from env.example. Edit secrets before first launch."
}

if (-not (Test-Path "mosquitto/passwordfile")) {
    New-Item -ItemType File -Force -Path "mosquitto/passwordfile" | Out-Null
}

docker compose pull
docker compose up -d

Write-Host "[deploy] Stack is running."
Write-Host "[deploy] Grafana: http://<EC2_PUBLIC_IP>:3000"
Write-Host "[deploy] MQTT broker: <EC2_PUBLIC_IP>:1883"
