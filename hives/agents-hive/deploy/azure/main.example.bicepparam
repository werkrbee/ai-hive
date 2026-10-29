// Copy to main.bicepparam (not committed) and fill in. No secrets go here.
using 'main.bicep'

// From entra.sh.
param apiAppId = '<api-app-id>'
param allowedClients = ['<lineup-client-app-id>', '<singularity-client-app-id>']

// Two Foundry models for the eval (README.md, "Choosing the model"); the server calls modelDeployment.
// Take format, name and version from the Foundry model catalog
// (az cognitiveservices model list -l <region>), and the sku and capacity the model
// offers there; deploy.sh refuses one that isn't GenerallyAvailable in the region. Add providerData to an entry whose provider
// requires it (README.md, step 2), e.g. for an Anthropic model:
//   providerData: { organizationName: '<legal entity>', countryCode: '<US>', industry: '<technology>' }
param models = [
  { deployment: 'review-a', format: '<format>', name: '<model-a>', version: '<version>', sku: 'GlobalStandard', capacity: 1 }
  { deployment: 'review-b', format: '<format>', name: '<model-b>', version: '<version>', sku: 'GlobalStandard', capacity: 1 }
]
param modelDeployment = 'review-a'   // its format sets the API the server speaks
param inputUsdPerMtok = '<list price, USD per million input tokens>'   // prices.sh looks it up
param outputUsdPerMtok = '<list price, USD per million output tokens>'

param monthlyCeilingUsd = '25'
param budgetUsd = 25
param budgetContactEmails = ['<you@example.com>']
param budgetStartDate = '2026-11-01'

// Patricia's weekly trust evaluation, as cron in UTC (default Mondays 06:00), and who may
// read the audit log's immutable copy: your object id, from az ad signed-in-user show --query id.
// param evalSchedule = '0 6 * * 1'
// param auditReaders = ['<your-object-id>']
