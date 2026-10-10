// werkrbee's deployment of the reference A2A server (hives/agents-hive/servers/a2a) for
// Patricia's governance-review. One resource group holds everything, so its budget covers
// the whole deployment. See README.md for the order to run things in.

targetScope = 'resourceGroup'

@description('Prefix for resource names, lowercase letters and digits.')
@minLength(3)
@maxLength(12)
param prefix string = 'patricia'

param location string = resourceGroup().location

@description('The Entra tenant that issues callers\' tokens.')
param tenantId string = subscription().tenantId

@description('Application (client) id of the API app registration, from entra.sh.')
param apiAppId string

@description('Application (client) ids of the products allowed to call, from entra.sh.')
@minLength(1)
param allowedClients array

@description('Container image, e.g. <registry>.azurecr.io/hive-a2a:<tag>. Empty deploys everything except the app, so the image can be built into the new registry first.')
param image string = ''

@description('Foundry model deployments. The server uses the one named by modelDeployment. Take format, name and version from the Foundry model catalog; some models need their terms accepted in the portal first.')
param models array

@description('Which entry in models the server calls.')
param modelDeployment string

@description('anthropic or openai: the API the chosen model is served through.')
@allowed(['anthropic', 'openai'])
param modelProvider string

@description('The chosen model\'s list price in USD per million input and output tokens, as strings (Bicep has no decimals). The server prices calls with them for its ledger and ceiling.')
param inputUsdPerMtok string
param outputUsdPerMtok string

@description('The server\'s own monthly ceiling on model spend, in USD (a string, for decimals).')
param monthlyCeilingUsd string = '25'

@description('Azure budget for this resource group, in USD a month. It alerts; it doesn\'t stop anything.')
param budgetUsd int = 25

@description('Where budget alerts go. Kept out of the repo: pass it at deploy time.')
@minLength(1)
param budgetContactEmails array

@description('First day of the budget, the first of a month, e.g. 2026-11-01.')
param budgetStartDate string

var suffix = uniqueString(resourceGroup().id)
var appName = '${prefix}-a2a'
var aiName = '${prefix}-ai-${suffix}'
var shareName = 'hive-a2a-data'

// Built-in role ids.
var acrPull = '7f951dde-4ef9-41c1-b0ac-8f2d6ec5c76b'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-a2a-id'
  location: location
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${prefix}acr${suffix}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource registryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPull)
  scope: registry
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

// Microsoft Foundry. Local (key) auth is off: the server reaches the model only with its
// managed identity, so there is no API key to store or leak.
resource ai 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: aiName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: aiName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

@batchSize(1)
resource deployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [for m in models: {
  parent: ai
  name: m.deployment
  sku: { name: m.sku, capacity: m.capacity }
  properties: {
    model: { format: m.format, name: m.name, version: m.version }
  }
}]

resource aiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(ai.id, identity.id, cognitiveServicesUser)
  scope: ai
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
  }
}

// Tasks (SQLite) and the usage ledger live on an Azure Files share, so they survive
// restarts and scale-to-zero.
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take('${prefix}st${suffix}', 24)
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource files 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: files
  name: shareName
  properties: { shareQuota: 1 }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    // Unauthenticated requests still wake the app and write logs, outside the server's
    // ledger. 0.1 GB a day keeps ingestion to a few dollars a month at most.
    workspaceCapping: { dailyQuotaGb: json('0.1') }
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource environmentShare 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: environment
  name: 'hive-a2a-data'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: shareName
      accessMode: 'ReadWrite'
    }
  }
}

var publicUrl = 'https://${appName}.${environment.properties.defaultDomain}/'
var chosen = filter(models, m => m.deployment == modelDeployment)
var baseUrl = modelProvider == 'anthropic'
  ? 'https://${aiName}.services.ai.azure.com/anthropic'
  : 'https://${aiName}.openai.azure.com/openai/v1'

resource app 'Microsoft.App/containerApps@2024-03-01' = if (!empty(image)) {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [registryPull, aiUser, deployments]
  properties: {
    environmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false // HTTPS only; plain HTTP is redirected
      }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
    }
    template: {
      containers: [{
        name: 'hive-a2a'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'PUBLIC_URL', value: publicUrl }
          { name: 'AZURE_TENANT_ID', value: tenantId }
          { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId } // DefaultAzureCredential picks this identity
          { name: 'API_APP_ID', value: apiAppId }
          { name: 'ALLOWED_CLIENTS', value: join(allowedClients, ',') }
          { name: 'MODEL_PROVIDER', value: modelProvider }
          { name: 'MODEL_NAME', value: chosen[0].deployment }
          { name: 'MODEL_BASE_URL', value: baseUrl }
          { name: 'MODEL_INPUT_USD_PER_MTOK', value: inputUsdPerMtok }
          { name: 'MODEL_OUTPUT_USD_PER_MTOK', value: outputUsdPerMtok }
          { name: 'MONTHLY_CEILING_USD', value: monthlyCeilingUsd }
          { name: 'DATA_DIR', value: '/data' }
        ]
        volumeMounts: [{ volumeName: 'data', mountPath: '/data' }]
        probes: [{
          type: 'Readiness'
          httpGet: { path: '/.well-known/agent-card.json', port: 8080 }
        }]
      }]
      volumes: [{
        name: 'data'
        storageType: 'AzureFile'
        storageName: environmentShare.name
        // SQLite needs byte-range locks SMB doesn't give it; nobrl is safe only with one
        // writer. See the README on the overlap while a new revision starts.
        mountOptions: 'nobrl,uid=1000,gid=1000,file_mode=0600,dir_mode=0700'
      }]
      // Scale to zero when idle. Never more than one replica: the ledger's running total
      // and the SQLite task store each belong to a single process.
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: '${prefix}-a2a-monthly'
  properties: {
    category: 'Cost'
    amount: budgetUsd
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      actual80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: budgetContactEmails
      }
      actual100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: budgetContactEmails
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: budgetContactEmails
      }
    }
  }
}

output registry string = registry.properties.loginServer
output publicUrl string = publicUrl
output agentCard string = '${publicUrl}.well-known/agent-card.json'
output foundryEndpoint string = ai.properties.endpoint
