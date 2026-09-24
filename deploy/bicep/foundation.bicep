// Production foundations (Phase 0 of docs/decisions/2026-09-24-azure-production.md).
//
// Everything production needs BEFORE a container runs: observability, the secret store, the identity the
// Container Apps read secrets with, the Container Apps environment, and Foundry with its model deployments.
// Declarative and idempotent: re-running it converges; nothing here is a one-off CLI step.
//
//   az deployment group create -g rg-lab-prod -f deploy/bicep/foundation.bicep -p deploy/bicep/foundation.prod.bicepparam
//
// Not here, deliberately: the Container Apps themselves (rendered from the one topology by deploy/aca.py,
// Phase 1), and every secret VALUE (a human writes those into Key Vault; GitHub holds no production secret).

targetScope = 'resourceGroup'

@description('Short environment name used in every resource name.')
param env string = 'prod'

param location string = resourceGroup().location

@description('Object id of the person who writes production secrets (Key Vault Secrets Officer).')
param vaultWriterObjectId string

@description('Log Analytics daily ingestion cap in GB — the cost ceiling for logs and traces.')
param logDailyQuotaGb int = 1

@description('Model deployments. sku GlobalStandard = processed in any Azure region (the stated exception); Standard = in-region.')
param deployments array

@description('Postgres admin password. Supplied at deploy time from Key Vault secret pg-admin-password, never stored in the repo.')
@secure()
param pgAdminPassword string

@description('Temporary client IPs allowed through the Postgres firewall (e.g. the operator restoring the dev copy). Empty after.')
param pgOperatorIps array = []

var suffix = uniqueString(resourceGroup().id)

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-lab-${env}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: logDailyQuotaGb }
  }
}

// The Foundry-observability analogue: every role's OTLP lands here (Jaeger stays a dev-only sink).
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-lab-${env}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'other'
    WorkspaceResourceId: logs.id
  }
}

// The identity every Container App uses to read ITS secrets (ROLE_ENV scopes which ones, per app).
resource appsIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-lab-${env}-apps'
  location: location
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-lab-${env}-${take(suffix, 6)}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enabledForTemplateDeployment: true   // lets a .bicepparam read secrets (getSecret) instead of a CLI argument
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
    enablePurgeProtection: true
  }
}

var kvSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var kvSecretsOfficer = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource appsReadSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, appsIdentity.id, kvSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUser)
    principalId: appsIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource humanWritesSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, vaultWriterObjectId, kvSecretsOfficer)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsOfficer)
    principalId: vaultWriterObjectId
    principalType: 'User'
  }
}

resource apps 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: 'cae-lab-${env}'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [ { name: 'Consumption', workloadProfileType: 'Consumption' } ]
  }
}

// Foundry: one AIServices account (the model endpoint the gateway calls) + one project.
resource foundry 'Microsoft.CognitiveServices/accounts@2026-05-01' = {
  name: 'aif-lab-${env}-${take(suffix, 6)}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-lab-${env}-${take(suffix, 6)}'
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' = {
  parent: foundry
  name: 'lab-${env}'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'lab ${env}'
    description: 'Production project for the local-agent-lab workloads.'
  }
}

// The apps' identity may call the models keylessly (the gateway's Phase-1 credential may still be a key).
resource appsCallModels 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, appsIdentity.id, cognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: appsIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// One at a time: parallel deployment writes on one account conflict.
@batchSize(1)
resource model 'Microsoft.CognitiveServices/accounts/deployments@2026-05-01' = [for d in deployments: {
  parent: foundry
  name: d.name
  sku: { name: d.sku, capacity: d.capacity }
  properties: {
    model: { format: d.format, name: d.model, version: d.version }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
  dependsOn: [ project ]
}]

// Postgres: the same Postgres 16 + pgvector as dev's Railway container, as a managed server. Not a container
// on Container Apps: its only volumes are Azure Files, and Postgres on SMB cannot chmod its data directory.
// It holds the gateway registry + artifacts (`litellm`) and the signed reference corpus (`reference`).
resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: 'psql-lab-${env}-${take(suffix, 6)}'
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    version: '16'
    administratorLogin: 'labadmin'
    administratorLoginPassword: pgAdminPassword
    storage: { storageSizeGB: 32, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
    authConfig: { activeDirectoryAuth: 'Disabled', passwordAuth: 'Enabled' }
  }
}

resource pgExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-08-01' = {
  parent: pg
  name: 'azure.extensions'
  properties: { value: 'VECTOR', source: 'user-override' }
}

// Container Apps on the Consumption profile have no fixed egress IP, so Phase 1 admits Azure-internal
// traffic (the 0.0.0.0 rule) behind TLS + password. VNet integration + private access is the hardening step.
resource pgAllowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2025-08-01' = {
  parent: pg
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
  dependsOn: [ pgExtensions ]
}

@batchSize(1)
resource pgOperator 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2025-08-01' = [for (ip, i) in pgOperatorIps: {
  parent: pg
  name: 'operator-${i}'
  properties: { startIpAddress: ip, endIpAddress: ip }
  dependsOn: [ pgAllowAzure ]
}]

@batchSize(1)
resource pgDatabases 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2025-08-01' = [for db in [ 'litellm', 'reference' ]: {
  parent: pg
  name: db
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [ pgOperator ]
}]

output pgHost string = pg.properties.fullyQualifiedDomainName
output foundryEndpoint string = foundry.properties.endpoint
output foundryName string = foundry.name
output vaultName string = vault.name
output vaultUri string = vault.properties.vaultUri
output appsIdentityId string = appsIdentity.id
output appsIdentityClientId string = appsIdentity.properties.clientId
output environmentId string = apps.id
output environmentDomain string = apps.properties.defaultDomain
output appInsightsConnectionString string = appInsights.properties.ConnectionString
