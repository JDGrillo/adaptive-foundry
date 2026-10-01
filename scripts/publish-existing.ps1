<#
.SYNOPSIS
    Publishes the hosted agent into an existing Microsoft Foundry project.
.DESCRIPTION
    Reads local defaults from src\adaptive-card-agent\.env, resolves and
    validates the existing Foundry project through Azure Resource Manager,
    configures a local azd environment, and deploys only adaptive-card-agent.

    This script never runs azd provision or azd up.
#>

[CmdletBinding()]
param(
    [ValidatePattern("^[a-zA-Z0-9-]+$")]
    [string] $EnvironmentName = "adaptive-card-demo",

    [string] $ProjectEndpoint,

    [ValidatePattern("^/subscriptions/")]
    [string] $ProjectId,

    [string] $ModelDeploymentName,

    [string] $SubscriptionId,

    [string] $TenantId,

    [switch] $SkipChecks,

    [switch] $ValidateOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$agentRoot = Join-Path $root "src\adaptive-card-agent"
$dotEnvPath = Join-Path $agentRoot ".env"
$projectApiVersion = "2025-06-01"

function Read-DotEnv {
    param([string] $Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return @{}
    }

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and
                (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                 ($value.StartsWith("'") -and $value.EndsWith("'")))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$Matches[1]] = $value
        }
    }
    return $values
}

function Invoke-AzJson {
    param(
        [Parameter(Mandatory)]
        [string[]] $Arguments
    )

    $output = & az @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "az $($Arguments -join ' ') failed:`n$($output -join "`n")"
    }
    if (-not $output) {
        return $null
    }
    return (($output -join "`n") | ConvertFrom-Json -ErrorAction Stop)
}

function Get-EndpointIdentity {
    param(
        [Parameter(Mandatory)]
        [string] $Endpoint
    )

    try {
        $uri = [System.Uri]$Endpoint.Trim().TrimEnd("/")
    }
    catch {
        throw "Project endpoint is not a valid URI: $Endpoint"
    }

    if ($uri.Scheme -ne "https") {
        throw "Project endpoint must use https."
    }

    $hostSuffix = ".services.ai.azure.com"
    if (-not $uri.Host.EndsWith($hostSuffix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Project endpoint host must end with '$hostSuffix'."
    }

    $accountName = $uri.Host.Substring(0, $uri.Host.Length - $hostSuffix.Length)
    $segments = @($uri.AbsolutePath.Trim("/").Split(
        "/",
        [System.StringSplitOptions]::RemoveEmptyEntries
    ))
    $projectIndex = [Array]::FindIndex(
        $segments,
        [Predicate[string]] { param($segment) $segment -ieq "projects" }
    )
    if ($projectIndex -lt 0 -or ($projectIndex + 1) -ge $segments.Count) {
        throw "Could not read a project name from endpoint '$Endpoint'."
    }

    return [pscustomobject]@{
        Endpoint = $uri.AbsoluteUri.TrimEnd("/")
        AccountName = $accountName
        ProjectName = [System.Uri]::UnescapeDataString($segments[$projectIndex + 1])
    }
}

function Get-ProjectIdParts {
    param(
        [Parameter(Mandatory)]
        [string] $ResourceId
    )

    $pattern = '^/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/Microsoft\.CognitiveServices/accounts/([^/]+)/projects/([^/]+)$'
    if ($ResourceId -notmatch $pattern) {
        throw "Project ID is not a Microsoft.CognitiveServices/accounts/projects resource ID."
    }

    return [pscustomobject]@{
        SubscriptionId = $Matches[1]
        ResourceGroup = $Matches[2]
        AccountName = $Matches[3]
        ProjectName = $Matches[4]
    }
}

function Get-AzdEnvironmentValues {
    param([string] $Name)

    $output = & azd env get-values --environment $Name 2>$null
    if ($LASTEXITCODE -ne 0) {
        return @{}
    }

    $values = @{}
    foreach ($line in $output) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$Matches[1]] = $value
        }
    }
    return $values
}

function Resolve-ExistingProjectId {
    param(
        [Parameter(Mandatory)]
        $EndpointIdentity,

        [string] $RequestedProjectId,

        [string] $RequestedSubscriptionId,

        [hashtable] $AzdValues
    )

    if ($RequestedProjectId) {
        return $RequestedProjectId
    }

    $azdEndpoint = $AzdValues["AZURE_AI_PROJECT_ENDPOINT"]
    $azdProjectId = $AzdValues["AZURE_AI_PROJECT_ID"]
    if ($azdProjectId -and
        $azdEndpoint -and
        $azdEndpoint.TrimEnd("/") -ieq $EndpointIdentity.Endpoint) {
        return $azdProjectId
    }

    $subscriptions = @()
    if ($RequestedSubscriptionId) {
        $subscriptions = @(Invoke-AzJson @(
            "account", "show",
            "--subscription", $RequestedSubscriptionId,
            "--output", "json",
            "--only-show-errors"
        ))
    }
    else {
        $subscriptions = @(Invoke-AzJson @(
            "account", "list",
            "--query", "[?state=='Enabled'].{id:id,tenantId:tenantId,name:name}",
            "--output", "json",
            "--only-show-errors"
        ))
    }

    $matches = @()
    foreach ($subscription in $subscriptions) {
        $accounts = @(Invoke-AzJson @(
            "cognitiveservices", "account", "list",
            "--subscription", $subscription.id,
            "--output", "json",
            "--only-show-errors"
        ))
        foreach ($account in $accounts) {
            if ($account.name -ine $EndpointIdentity.AccountName -and
                $account.properties.customSubDomainName -ine $EndpointIdentity.AccountName) {
                continue
            }

            $candidateId = "$($account.id)/projects/$($EndpointIdentity.ProjectName)"
            $url = "https://management.azure.com${candidateId}?api-version=$projectApiVersion"
            $project = & az rest --method get --url $url --output json --only-show-errors 2>$null
            if ($LASTEXITCODE -eq 0 -and $project) {
                $projectObject = ($project -join "`n") | ConvertFrom-Json
                if ($projectObject.id) {
                    $matches += $projectObject.id
                }
            }
        }
    }

    if ($matches.Count -eq 0) {
        throw "Could not find existing Foundry project '$($EndpointIdentity.ProjectName)' under account '$($EndpointIdentity.AccountName)' in the accessible Azure subscriptions. Supply -ProjectId or sign Azure CLI into the subscription that owns the project."
    }
    if ($matches.Count -gt 1) {
        throw "Multiple existing Foundry projects matched the endpoint. Supply -ProjectId or -SubscriptionId."
    }

    return $matches[0]
}

function Test-ExistingProject {
    param(
        [Parameter(Mandatory)]
        [string] $ResourceId,

        [Parameter(Mandatory)]
        $EndpointIdentity
    )

    $parts = Get-ProjectIdParts $ResourceId
    if ($parts.AccountName -ine $EndpointIdentity.AccountName -or
        $parts.ProjectName -ine $EndpointIdentity.ProjectName) {
        throw "Project ID does not match endpoint account/project '$($EndpointIdentity.AccountName)/$($EndpointIdentity.ProjectName)'."
    }

    $url = "https://management.azure.com${ResourceId}?api-version=$projectApiVersion"
    $project = Invoke-AzJson @(
        "rest",
        "--method", "get",
        "--url", $url,
        "--output", "json",
        "--only-show-errors"
    )
    if (-not $project.id -or $project.id -ine $ResourceId) {
        throw "Azure did not return the expected existing Foundry project '$ResourceId'."
    }
    if (-not $project.location) {
        throw "Azure did not return a location for the existing Foundry project '$ResourceId'."
    }

    return [pscustomobject]@{
        SubscriptionId = $parts.SubscriptionId
        ResourceGroup = $parts.ResourceGroup
        AccountName = $parts.AccountName
        ProjectName = $parts.ProjectName
        Location = [string]$project.location
    }
}

foreach ($command in @("az", "azd")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "'$command' is required and was not found on PATH."
    }
}

$localValues = Read-DotEnv $dotEnvPath
if (-not $ProjectEndpoint) {
    $ProjectEndpoint = $localValues["FOUNDRY_PROJECT_ENDPOINT"]
}
if (-not $ModelDeploymentName) {
    $ModelDeploymentName = $localValues["AZURE_AI_MODEL_DEPLOYMENT_NAME"]
}
if (-not $ProjectEndpoint) {
    throw "Project endpoint was not supplied and FOUNDRY_PROJECT_ENDPOINT was not found in $dotEnvPath."
}

$endpointIdentity = Get-EndpointIdentity $ProjectEndpoint

Push-Location $root
try {
    $env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"

    if (-not $SkipChecks) {
        & (Join-Path $PSScriptRoot "check.ps1")
        if ($LASTEXITCODE -ne 0) {
            throw "Local validation failed."
        }
    }

    $azdValues = Get-AzdEnvironmentValues $EnvironmentName
    $ProjectId = Resolve-ExistingProjectId `
        -EndpointIdentity $endpointIdentity `
        -RequestedProjectId $ProjectId `
        -RequestedSubscriptionId $SubscriptionId `
        -AzdValues $azdValues

    $projectParts = Test-ExistingProject `
        -ResourceId $ProjectId `
        -EndpointIdentity $endpointIdentity

    if ($SubscriptionId -and $SubscriptionId -ine $projectParts.SubscriptionId) {
        throw "Subscription '$SubscriptionId' does not match project subscription '$($projectParts.SubscriptionId)'."
    }
    $SubscriptionId = $projectParts.SubscriptionId

    $subscription = Invoke-AzJson @(
        "account", "show",
        "--subscription", $SubscriptionId,
        "--output", "json",
        "--only-show-errors"
    )
    if (-not $TenantId) {
        $TenantId = $subscription.tenantId
    }
    elseif ($TenantId -ine $subscription.tenantId) {
        throw "Tenant '$TenantId' does not match the tenant for subscription '$SubscriptionId'."
    }

    if ($ValidateOnly) {
        Write-Host "Existing Foundry project validated:"
        Write-Host "  Resource ID: $ProjectId"
        Write-Host "  Endpoint:    $($endpointIdentity.Endpoint)"
        Write-Host "  Location:    $($projectParts.Location)"
        Write-Host "No azd environment values were changed and no agent was deployed."
        return
    }

    & azd env select $EnvironmentName 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Creating local azd environment '$EnvironmentName' (no Azure resources are created)."
        & azd env new $EnvironmentName --subscription $SubscriptionId --no-prompt
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create local azd environment '$EnvironmentName'."
        }
    }

    $settings = [ordered]@{
        AZURE_SUBSCRIPTION_ID = $SubscriptionId
        AZURE_TENANT_ID = $TenantId
        AZURE_RESOURCE_GROUP = $projectParts.ResourceGroup
        AZURE_AI_ACCOUNT_NAME = $projectParts.AccountName
        AZURE_AI_PROJECT_NAME = $projectParts.ProjectName
        AZURE_LOCATION = $projectParts.Location
        AZURE_AI_PROJECT_ID = $ProjectId
        AZURE_AI_PROJECT_ENDPOINT = $endpointIdentity.Endpoint
        FOUNDRY_PROJECT_ENDPOINT = $endpointIdentity.Endpoint
    }
    if ($ModelDeploymentName) {
        $settings["AZURE_AI_MODEL_DEPLOYMENT_NAME"] = $ModelDeploymentName
    }

    foreach ($entry in $settings.GetEnumerator()) {
        & azd env set $entry.Key $entry.Value --environment $EnvironmentName
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to set azd environment value '$($entry.Key)'."
        }
    }

    $resolvedProject = & azd ai project show `
        --environment $EnvironmentName `
        --output json `
        --no-prompt |
        ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or
        $resolvedProject.endpoint.TrimEnd("/") -ine $endpointIdentity.Endpoint) {
        throw "azd did not resolve the expected existing Foundry project endpoint."
    }

    Write-Host ""
    Write-Host "Publishing only hosted agent 'adaptive-card-agent'."
    Write-Host "Existing project: $ProjectId"
    Write-Host "No infrastructure provisioning command is used."

    & azd deploy adaptive-card-agent `
        --environment $EnvironmentName `
        --no-prompt
    if ($LASTEXITCODE -ne 0) {
        throw "Foundry hosted-agent deployment failed."
    }

    & azd ai agent show adaptive-card-agent `
        --environment $EnvironmentName `
        --output json `
        --no-prompt
    if ($LASTEXITCODE -ne 0) {
        throw "Deployment completed, but agent status verification failed."
    }
}
finally {
    Remove-Item Env:\AZURE_DEV_USER_AGENT -ErrorAction SilentlyContinue
    Pop-Location
}
