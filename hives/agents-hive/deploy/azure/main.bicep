// werkrbee's deployment of the reference A2A server (hives/agents-hive/servers/a2a) for
// Patricia's governance-review and, when barry is set, hosted Barry's orchestration beside
// her, with the MCP server he is checked against. One resource group holds everything, so
// its budget covers the whole deployment. See README.md for the order to run things in.

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

@description('Foundry model deployments. The server uses the one named by modelDeployment. Take format, name, version and sku from the Foundry model catalog for the region; deploy.sh refuses a model that isn\'t generally available there. Some models need their terms accepted in the portal first. An entry may add providerData, which Foundry passes to the model\'s provider; some providers require it (README.md, step 2).')
param models array

@description('Which entry in models the server calls. Its format decides the API the server speaks: Anthropic models are served through the Messages API, every other format through Chat Completions.')
param modelDeployment string

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

@description('When Patricia\'s weekly trust evaluation runs, as a cron expression in UTC. Mondays at 06:00 by default.')
param evalSchedule string = '0 6 * * 1'

@description('Object ids of the people who may read the immutable copy of the audit log (audit_blob.py check), e.g. from az ad signed-in-user show --query id. The job writes it; nobody else needs to.')
param auditReaders array = []

@description('Hosted Barry, beside Patricia, from the same image and model. Empty deploys Patricia alone. apiAppId and allowedClients come from entra.sh --agent barry; callers maps each allowed client to its registration (registrations/<name>), as [{ client, registration }]; verifyApiAppId is the verify MCP server\'s API app, from entra.sh --agent verify; monthlyCeilingUsd is his own ceiling (a string, default 15).')
param barry object = {}

var suffix = uniqueString(resourceGroup().id)
var appName = '${prefix}-a2a'
var aiName = '${prefix}-ai-${suffix}'
var shareName = 'hive-a2a-data'
var auditContainer = 'audit'

// The formats served only through the Messages API. The catalog doesn't say which API a
// model needs, so this list is the rule; add a publisher here if it needs Messages too.
// deploy.sh reads this line to show each model's API before the what-if.
var messagesFormats = ['Anthropic']
var chosen = filter(models, m => m.deployment == modelDeployment)
var modelApi = contains(messagesFormats, chosen[0].format) ? 'messages' : 'chat-completions'

var barryOn = !empty(barry)
var barryName = 'barry-a2a'
var verifyName = 'barry-verify'
var barryShareName = 'hive-barry-data'

// Built-in role ids.
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var cognitiveServicesOpenAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageBlobDataReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

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

// Barry's identity, separate from Patricia's, holds only what he uses: AcrPull here and
// Foundry access below. Tokens for Patricia's API and the verify server's are app roles
// granted to it in Entra (entra.sh --identity), not Azure roles. The verify server's
// identity only pulls the image.
resource barryIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = if (barryOn) {
  name: '${barryName}-id'
  location: location
}

resource barryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (barryOn) {
  name: guid(registry.id, '${barryName}-id', acrPull)
  scope: registry
  properties: {
    principalId: barryIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

resource verifyIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = if (barryOn) {
  name: '${verifyName}-id'
  location: location
}

resource verifyPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (barryOn) {
  name: guid(registry.id, '${verifyName}-id', acrPull)
  scope: registry
  properties: {
    principalId: verifyIdentity!.properties.principalId
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
resource deployments 'Microsoft.CognitiveServices/accounts/deployments@2026-09-01' = [for m in models: {
  parent: ai
  name: m.deployment
  sku: { name: m.sku, capacity: m.capacity }
  properties: union(
    { model: { format: m.format, name: m.name, version: m.version } },
    contains(m, 'providerData') ? { modelProviderData: m.providerData } : {}
  )
}]

// The narrowest built-in role each route allows. Cognitive Services OpenAI User covers the
// OpenAI v1 endpoint, without listKeys or the other data actions; Claude's /anthropic
// endpoint isn't under it and needs Cognitive Services User (README.md, Resources).
resource aiOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (modelApi == 'chat-completions') {
  name: guid(ai.id, identity.id, cognitiveServicesOpenAiUser)
  scope: ai
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUser)
  }
}

resource aiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (modelApi == 'messages') {
  name: guid(ai.id, identity.id, cognitiveServicesUser)
  scope: ai
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
  }
}

// Barry calls the same model deployment, with the same narrowest role for its route.
resource barryAiOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (barryOn && modelApi == 'chat-completions') {
  name: guid(ai.id, '${barryName}-id', cognitiveServicesOpenAiUser)
  scope: ai
  properties: {
    principalId: barryIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUser)
  }
}

resource barryAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (barryOn && modelApi == 'messages') {
  name: guid(ai.id, '${barryName}-id', cognitiveServicesUser)
  scope: ai
  properties: {
    principalId: barryIdentity!.properties.principalId
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

// Barry's tasks, ledger and run records, on a share of his own: a ledger and a task store
// each belong to one server process.
resource barryShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = if (barryOn) {
  parent: files
  name: barryShareName
  properties: { shareQuota: 1 }
}

// The audit log's immutable copy, in a storage account of its own: once its retention policy
// is locked, the account can't be deleted until the period ends, and nothing else should be
// held with it. Only Entra identities reach it, no account key. deploy.sh sets the policy
// (365 days, protected append writes allowed) after this step, and locks it only when asked.
resource auditStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take('${prefix}log${suffix}', 24)
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    supportsHttpsTrafficOnly: true
  }
}

resource auditBlobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: auditStorage
  name: 'default'
}

resource audit 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: auditBlobs
  name: auditContainer
  properties: { publicAccess: 'None' }
}

// The job appends to the copy. Under the retention policy, a contributor can add blocks
// but can't change or delete them.
resource auditWrite 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(audit.id, identity.id, storageBlobDataContributor)
  scope: audit
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributor)
  }
}

resource auditRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for reader in auditReaders: {
  name: guid(audit.id, reader, storageBlobDataReader)
  scope: audit
  properties: {
    principalId: reader
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReader)
  }
}]

var auditBlobUrl = '${auditStorage.properties.primaryEndpoints.blob}${auditContainer}/patricia.jsonl'

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

resource barryEnvironmentShare 'Microsoft.App/managedEnvironments/storages@2024-03-01' = if (barryOn) {
  parent: environment
  name: barryShareName
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: barryShareName
      accessMode: 'ReadWrite'
    }
  }
}

var publicUrl = 'https://${appName}.${environment.properties.defaultDomain}/'
var barryUrl = 'https://${barryName}.${environment.properties.defaultDomain}/'
var verifyUrl = 'https://${verifyName}.${environment.properties.defaultDomain}/'
var barryClient = barryOn ? barryIdentity!.properties.clientId : ''
var baseUrl = modelApi == 'messages'
  ? 'https://${aiName}.services.ai.azure.com/anthropic'
  : 'https://${aiName}.openai.azure.com/openai/v1'

// What the app and the weekly job both start from (render_config.py).
var serverEnv = [
  { name: 'PUBLIC_URL', value: publicUrl }
  { name: 'AZURE_TENANT_ID', value: tenantId }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId } // DefaultAzureCredential picks this identity
  { name: 'API_APP_ID', value: apiAppId }
  // Barry calls Patricia as a client in his own right, with his identity's token.
  { name: 'ALLOWED_CLIENTS', value: join(concat(allowedClients, barryOn ? [barryClient] : []), ',') }
  { name: 'MODEL_API', value: modelApi }
  { name: 'MODEL_PUBLISHER', value: chosen[0].format } // for the ledger
  { name: 'MODEL_NAME', value: chosen[0].deployment }
  { name: 'MODEL_BASE_URL', value: baseUrl }
  { name: 'MODEL_INPUT_USD_PER_MTOK', value: inputUsdPerMtok }
  { name: 'MODEL_OUTPUT_USD_PER_MTOK', value: outputUsdPerMtok }
  { name: 'MONTHLY_CEILING_USD', value: monthlyCeilingUsd }
  { name: 'DATA_DIR', value: '/data' }
]
var dataVolume = {
  name: 'data'
  storageType: 'AzureFile'
  storageName: environmentShare.name
  // SQLite needs byte-range locks SMB doesn't give it; nobrl is safe only with one
  // writer. See the README on the overlap while a new revision starts. The job writes
  // only its own files: its ledger and assurance/.
  mountOptions: 'nobrl,uid=1000,gid=1000,file_mode=0600,dir_mode=0700'
}

resource app 'Microsoft.App/containerApps@2024-03-01' = if (!empty(image)) {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [registryPull, aiOpenAiUser, aiUser, deployments]
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
        // The weekly job's spending counts toward the server's ceiling.
        env: concat(serverEnv, [{ name: 'SHARED_LEDGERS', value: '/data/ledger-eval.jsonl' }])
        volumeMounts: [{ volumeName: 'data', mountPath: '/data' }]
        probes: [{
          type: 'Readiness'
          httpGet: { path: '/.well-known/agent-card.json', port: 8080 }
        }]
      }]
      volumes: [dataVolume]
      // Scale to zero when idle. Never more than one replica: the ledger's running total
      // and the SQLite task store each belong to a single process.
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

// Patricia's weekly trust evaluation (eval/weekly.sh), from the image the app runs, under
// her identity, in the same environment, so no credential goes into CI. It keeps its own
// ledger on the share and counts the server's toward the same ceiling, and pushes its audit
// log to the immutable copy. One replica, never retried: a failed run is a finding, not
// something to repeat.
resource evalJob 'Microsoft.App/jobs@2024-03-01' = if (!empty(image)) {
  name: '${prefix}-eval'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [registryPull, aiOpenAiUser, aiUser, deployments, auditWrite]
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Schedule'
      scheduleTriggerConfig: { cronExpression: evalSchedule, parallelism: 1, replicaCompletionCount: 1 }
      replicaTimeout: 1800
      replicaRetryLimit: 0
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
    }
    template: {
      containers: [{
        name: 'hive-eval'
        image: image
        command: ['sh', '/app/hives/agents-hive/deploy/azure/eval/weekly.sh']
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: concat(serverEnv, [
          { name: 'LEDGER', value: '/data/ledger-eval.jsonl' }
          { name: 'SHARED_LEDGERS', value: '/data/ledger.jsonl' }
          { name: 'ASSURANCE_DIR', value: '/data/assurance' }
          { name: 'AUDIT_BLOB_URL', value: auditBlobUrl }
          { name: 'HIVE_COMMIT', value: last(split(image, ':')) } // the image's tag is its commit
        ])
        volumeMounts: [{ volumeName: 'data', mountPath: '/data' }]
      }]
      volumes: [dataVolume]
    }
  }
}

// Hosted Barry: the same image and model as Patricia, his own identity, share and ceiling.
var barryEnv = [
  { name: 'PERSONA', value: 'barry' }
  { name: 'PUBLIC_URL', value: barryUrl }
  { name: 'AZURE_TENANT_ID', value: tenantId }
  { name: 'AZURE_CLIENT_ID', value: barryClient }
  { name: 'API_APP_ID', value: barry.?apiAppId ?? '' }
  { name: 'ALLOWED_CLIENTS', value: join(barry.?allowedClients ?? [], ',') }
  { name: 'MODEL_API', value: modelApi }
  { name: 'MODEL_PUBLISHER', value: chosen[0].format }
  { name: 'MODEL_NAME', value: chosen[0].deployment }
  { name: 'MODEL_BASE_URL', value: baseUrl }
  { name: 'MODEL_INPUT_USD_PER_MTOK', value: inputUsdPerMtok }
  { name: 'MODEL_OUTPUT_USD_PER_MTOK', value: outputUsdPerMtok }
  { name: 'MONTHLY_CEILING_USD', value: barry.?monthlyCeilingUsd ?? '15' }
  { name: 'DATA_DIR', value: '/data' }
  { name: 'PATRICIA_URL', value: publicUrl }
  { name: 'PATRICIA_API_APP_ID', value: apiAppId }
  { name: 'CALLERS', value: join(map(barry.?callers ?? [], c => '${c.client}=${c.registration}'), ',') }
]

resource barryApp 'Microsoft.App/containerApps@2024-03-01' = if (barryOn && !empty(image)) {
  name: barryName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${barryIdentity.id}': {} }
  }
  dependsOn: [barryPull, barryAiOpenAiUser, barryAiUser, deployments]
  properties: {
    environmentId: environment.id
    configuration: {
      ingress: { external: true, targetPort: 8080, transport: 'http', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: barryIdentity.id }]
    }
    template: {
      containers: [{
        name: 'hive-a2a'
        image: image
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: barryEnv
        volumeMounts: [{ volumeName: 'data', mountPath: '/data' }]
        probes: [{
          type: 'Readiness'
          httpGet: { path: '/.well-known/agent-card.json', port: 8080 }
        }]
      }]
      volumes: [{
        name: 'data'
        storageType: 'AzureFile'
        storageName: barryEnvironmentShare.name
        mountOptions: 'nobrl,uid=1000,gid=1000,file_mode=0600,dir_mode=0700'
      }]
      // One replica, for the same reason as Patricia's: one ledger, one task store.
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

// The MCP server Barry is checked against (servers/verify-mcp): one gated tool that keeps a
// note in memory. It accepts only Barry's identity, with the Verify.Call role.
resource verifyApp 'Microsoft.App/containerApps@2024-03-01' = if (barryOn && !empty(image)) {
  name: verifyName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${verifyIdentity.id}': {} }
  }
  dependsOn: [verifyPull]
  properties: {
    environmentId: environment.id
    configuration: {
      ingress: { external: true, targetPort: 8080, transport: 'http', allowInsecure: false }
      registries: [{ server: registry.properties.loginServer, identity: verifyIdentity.id }]
    }
    template: {
      containers: [{
        name: 'verify-mcp'
        image: image
        command: ['python', '/app/hives/agents-hive/servers/verify-mcp/verify_mcp.py', '--host', '0.0.0.0', '--port', '8080']
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        env: [
          { name: 'PUBLIC_URL', value: verifyUrl }
          { name: 'AZURE_TENANT_ID', value: tenantId }
          { name: 'API_APP_ID', value: barry.?verifyApiAppId ?? '' }
          { name: 'ALLOWED_CLIENTS', value: barryClient }
        ]
        probes: [{
          type: 'Readiness'
          httpGet: { path: '/.well-known/mcp/server-card.json', port: 8080 }
        }]
      }]
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
output dataAccount string = storage.name
output auditAccount string = auditStorage.name
output auditContainer string = auditContainer
output auditBlobUrl string = auditBlobUrl
output barryUrl string = barryOn ? barryUrl : ''
output barryAgentCard string = barryOn ? '${barryUrl}.well-known/agent-card.json' : ''
output barryPrincipalId string = barryOn ? barryIdentity!.properties.principalId : ''
output verifyUrl string = barryOn ? verifyUrl : ''
