// Production's gateway: Azure API Management, Developer tier, UAE North (docs/decisions/2026-09-24-azure-production.md,
// Phase 2). Production runs on APIM ONLY and dev on LiteLLM only — the two never meet (user, 24 Sep 2026).
//
// This file is the INSTANCE: tier, identity, and its right to call Foundry. The APIs, operations and policies are
// rendered from the lab's own tables (the /api role table, the model aliases, the MCP servers) into their own
// deployment, so the instance — a 30-40 minute create — is never rebuilt to change a route.
//
// Developer has no SLA and cannot be upgraded to a v2 tier: moving to Basic v2 later is a NEW instance from this
// file with `sku` changed, which is why nothing about the gateway lives anywhere but here and the rendered policies.
//
//   az deployment group create -g rg-lab-prod -n apim -f deploy/bicep/apim.bicep -p deploy/bicep/apim.prod.bicepparam

targetScope = 'resourceGroup'

param env string = 'prod'
param location string = resourceGroup().location
param sku string = 'Developer'
param publisherEmail string
param publisherName string = 'Agent Lab'

@description('The Foundry (AIServices) account APIM calls with its managed identity — no key anywhere.')
param foundryName string

var suffix = uniqueString(resourceGroup().id)
var cognitiveServicesUser = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: 'apim-lab-${env}-${take(suffix, 6)}'
  location: location
  sku: { name: sku, capacity: 1 }
  identity: { type: 'SystemAssigned' }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: foundryName
}

resource apimCallsModels 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, apim.id, cognitiveServicesUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUser)
    principalId: apim.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output apimName string = apim.name
output gatewayUrl string = apim.properties.gatewayUrl
output principalId string = apim.identity.principalId
