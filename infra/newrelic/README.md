# Root Terraform New Relic

Este root gerencia exclusivamente `helm_release.newrelic_kubernetes`, dashboards, alert policy/conditions NRQL e Synthetic. Não cria nem importa VPC, EKS, node group, RDS ou API Gateway. O EKS é consultado por data sources AWS com o nome fornecido externamente; o Secret Kubernetes é apenas validado e referenciado pelo nome.

## Recursos de observabilidade declarados

`ENABLE_NEWRELIC_KUBERNETES` (default `false`) habilita o chart `nri-bundle`, incluindo coleta Kubernetes e Fluent Bit
para logs do namespace configurado. A aplicação configura o agente APM Java e emite eventos de OS e integração.

`ENABLE_NEWRELIC_ACCOUNT_RESOURCES` (default `false`) habilita o dashboard privado e as condições NRQL para OS criadas/dia,
duração por etapa, latência APM, CPU/memória, falhas de processamento e integrações. Consultas opcionais definem widgets
e alertas de disponibilidade, CPU e memória. Synthetic requer URL e locations; o monitor é configurado para executar a
cada cinco minutos. Os recursos são provisionados pelo Apply do root.

Os widgets APM do dashboard filtram `environment`; as condições APM filtram `tags.environment`. Ajuste as consultas de
acordo com os atributos emitidos pelo agente. Este root não declara workflow/destino de notificação; no root API Gateway,
`alarm_actions` é vazio por padrão.

A aplicação emite `AutoFlowOrderCreated`, `AutoFlowOrderStageCompleted`, `AutoFlowOrderProcessingFailure` e
`AutoFlowIntegrationFailure`, todos com o atributo `environment`. Os logs JSON incluem `request.id` e, quando disponíveis,
`trace.id`/`span.id`.

### Coleta e parsing dos logs do backend

O `newrelic-logging` permanece em `lowDataMode` e coleta os arquivos stdout dos containers no namespace configurado. O filtro
customizado habilita `Merge_Log` para interpretar cada linha JSON antes da allowlist. São preservados somente os campos de
correlação/diagnóstico (`service.name`, `deployment.environment`, `request.id`, `trace.id`, `span.id`, timestamp, nível,
logger, mensagem e tipo da exceção) e os metadados Kubernetes necessários. Labels e annotations continuam desabilitados;
campos arbitrários, incluindo nomes associados a dados sensíveis, não são adicionados à allowlist. A allowlist não substitui
a sanitização da aplicação: mensagens e exceções devem continuar sem CPF/CNPJ, JWT, Authorization, senhas ou conteúdo de
requisição.

O Java APM mantém `NEW_RELIC_APPLICATION_LOGGING_ENABLED=true` e decoração local habilitada, mas
`NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED=false`. O único encaminhador é o Fluent Bit do `nri-bundle`; não habilite
forwarding paralelo no agente.

### Configuração esperada em homologação

- `ENABLE_NEWRELIC_KUBERNETES=true` no Environment `homolog`, com namespace `default`; a seleção efetiva é validada pelo
  Plan aprovado. O namespace das workloads deve coincidir com `newrelic_namespace`.
- O Secret existente `newrelic-license`, chave `licenseKey`, é referenciado pelo chart e pelo backend sem ler ou alterar seu
  conteúdo. A License Key é usada para ingestão; `NEW_RELIC_API_KEY` é uma User API key separada, usada pelo provider
  Terraform e não deve ser configurada no container.
- O ConfigMap `autoflow-config` fornece `SPRING_APPLICATION_NAME=autoflow-backend` e
  `DEPLOYMENT_ENVIRONMENT=homolog`. O backend grava JSON no stdout; não é necessário montar arquivo de log.
- Não definir exclusões adicionais de namespace/container que atinjam `default` ou `autoflow-backend`. A regra versionada
  limita a coleta ao namespace selecionado.

### Validação pós-aplicação no New Relic

Após o Apply autorizado do root New Relic e o rollout saudável do Fluent Bit (não executados nesta investigação), aguarde
alguns minutos e valide primeiro a ingestão sem retornar conteúdo de mensagens. Não é necessário republicar o backend se os
pods atuais já estiverem emitindo logs no stdout:

```nrql
SELECT count(*) FROM Log SINCE 1 hour ago
```

Confira os nomes reais de atributos sem inspecionar valores:

```nrql
SELECT keyset() FROM Log SINCE 1 hour ago
```

Depois valide os campos estruturados do backend:

```nrql
SELECT count(*) FROM Log
WHERE service.name = 'autoflow-backend'
  AND deployment.environment = 'homolog'
SINCE 1 hour ago
```

Confirme os metadados de pod/container com os nomes de atributo mostrados pelo `keyset()`; o formato pode variar com a versão
do coletor. Por fim, confira a correlação sem consultar mensagens não redigidas:

```nrql
SELECT timestamp, level, request.id, trace.id, span.id FROM Log
WHERE service.name = 'autoflow-backend'
  AND deployment.environment = 'homolog'
SINCE 1 hour ago LIMIT 20
```

`request.id` deve acompanhar os logs emitidos durante uma requisição; `trace.id`/`span.id` podem estar ausentes quando não há
transação APM associada. O widget versionado também inclui `message`; inspecione-o somente em eventos conhecidos e já
sanitizados. Se a primeira consulta tiver dados, mas as consultas por serviço não, use `keyset()` para diagnosticar parsing
ou nomes divergentes antes de alterar o NRQL do dashboard. Se a primeira consulta continuar sem logs do backend, verifique
namespace, configuração renderizada do Fluent Bit e erros do output plugin; não habilite um segundo forwarder.

## State e providers

- Backend S3 independente: bucket e key exclusivos fornecidos por Variables do GitHub Environment selecionado. A key deve começar com `homolog/` ou `production/`; seu sufixo é definido externamente e não é fixado neste root.
- Este root não cria o bucket. Se estiver ausente, execute primeiro o [bootstrap S3 isolado](../../docs/state-bucket-bootstrap.md); o workflow New Relic não faz bootstrap implícito.
- Providers travados: AWS `5.100.0`, Helm `3.3.0` e New Relic `3.100.5`. O lockfile mantém checksums `h1` e `zh` existentes, inclusive plataformas Linux e Windows.
- Inicialização local para validação sem backend: `terraform -chdir=infra/newrelic init -backend=false -input=false -lockfile=readonly`.

## Configuração externa

Reutiliza `AWS_REGION`, `AWS_EXPECTED_ACCOUNT_ID`, credenciais AWS, `AWS_TERRAFORM_STATE_BUCKET`, `TERRAFORM_PLAN_ENCRYPTION_PASSPHRASE` e `TERRAFORM_APPLY_APPROVAL_CONFIGURED`. Configure `AWS_TF_STATE_KEY_NEWRELIC` e os demais valores próprios em cada GitHub Environment (`homolog` ou `production`). O preflight verifica os valores resolvidos pelos contextos `vars`/`secrets`, sem consultar APIs administrativas para enumerar seu escopo. O nome do cluster EKS é descoberto após validar conta/região; não configure `EKS_CLUSTER_NAME`. Os inputs New Relic existentes (`ENABLE_NEWRELIC_KUBERNETES`, `ENABLE_NEWRELIC_ACCOUNT_RESOURCES`, account/region/API key, Synthetic e consultas opcionais) são consumidos por `newrelic.yml`; `NEW_RELIC_API_KEY` é User API key, não License Key, e é exigida para confirmar ausência de objetos remotos antes de criar.

O namespace `default`, Secret `newrelic-license`/chave `licenseKey`, release `newrelic-kubernetes` e chart `nri-bundle` versão `8.0.32` preservam a configuração existente. Antes de habilitar qualquer recurso New Relic, o workflow exige EKS e node groups `ACTIVE`, conectividade Kubernetes, Deployments `autoflow-backend`/`autoflow-frontend` com todas as réplicas disponíveis e Services internos existentes. Para `ENABLE_NEWRELIC_KUBERNETES=true`, também exige Secret não vazio.

O inventário remoto pagina dashboards via NerdGraph e alertas, condições NRQL e Synthetic via endpoints REST. Valida conta e ambiente, relaciona IDs somente em arquivos temporários protegidos e bloqueia falhas HTTP, GraphQL, cursores inválidos, páginas incompletas, duplicidade e identidades divergentes. `State` com `instances: []` não representa objeto existente.

## Execução

O workflow `.github/workflows/ci.yml` valida o root em Pull Requests para `develop`/`main` e pushes para `develop`, `main`
e `feature/**`, sem acesso AWS. `New Relic Pipeline` recebe `push` em `develop`/`main` e `workflow_dispatch`; o caminho
automático exige `AUTO_CD_ENABLED_HOMOLOG=true` em `develop` ou `AUTO_CD_ENABLED_PRODUCTION=true` em `main`, além de CI
bem-sucedida para o mesmo SHA, e executa somente Plan. Apply exige dispatch
com `apply=true` e `TERRAFORM_APPLY_APPROVAL_CONFIGURED=true`; o job usa o Environment selecionado. Configure Required
reviewers e restrições de branch para proteger o deployment. O Plan é criptografado e publicado em artifact vinculado ao
commit. `approve_reconciliation` gera imports declarativos incluídos no Plan; scripts não alteram State. Exclusões e
substituições exigem autorização e revisão do Plan.

Antes do primeiro uso, confirmar conta, ambiente e ownership. A pipeline bloqueia State legado, ownership duplicado, identidade ambígua, respostas incompletas e inventário inconclusivo. Divergência exige `workflow_dispatch` com `approve_reconciliation=true` e revisão do Plan; imports são declarativos e incluídos no mesmo Plan aprovado. A reconciliação não executa `state rm`, `state mv`, importação fora do Terraform ou Apply automático.
