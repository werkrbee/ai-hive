// Copy to main.bicepparam (not committed) and fill in. No secrets go here.
using 'main.bicep'

// From entra.sh.
param apiAppId = '<api-app-id>'
param allowedClients = ['<lineup-client-app-id>', '<singularity-client-app-id>']

// Two Foundry models for the eval (eval/README.md); the server calls modelDeployment.
// Take format, name and version from the Foundry model catalog, and the sku and
// capacity the model offers in your region.
param models = [
  { deployment: 'review-a', format: '<format>', name: '<model-a>', version: '<version>', sku: 'GlobalStandard', capacity: 1 }
  { deployment: 'review-b', format: '<format>', name: '<model-b>', version: '<version>', sku: 'GlobalStandard', capacity: 1 }
]
param modelDeployment = 'review-a'
param modelProvider = 'anthropic'   // anthropic or openai, for modelDeployment
param inputUsdPerMtok = '<list price, USD per million input tokens>'
param outputUsdPerMtok = '<list price, USD per million output tokens>'

param monthlyCeilingUsd = '25'
param budgetUsd = 25
param budgetContactEmails = ['<you@example.com>']
param budgetStartDate = '2026-11-01'
