# Changelog

## [0.9.0](https://github.com/werkrbee/ai-hive/compare/v0.8.0...v0.9.0) (2026-11-01)


### Features

* **agents-hive:** add hosted Barry's orchestration eval ([#173](https://github.com/werkrbee/ai-hive/issues/173)) ([a5c6e37](https://github.com/werkrbee/ai-hive/commit/a5c6e3782133bdf69320f08039143dbac2917282)), closes [#119](https://github.com/werkrbee/ai-hive/issues/119)
* **agents-hive:** add the orchestration executor ([#171](https://github.com/werkrbee/ai-hive/issues/171)) ([08edb52](https://github.com/werkrbee/ai-hive/commit/08edb526a44889ec7dd18d0dca70ded8b73f1d96))
* **agents-hive:** carry approvals over A2A ([#172](https://github.com/werkrbee/ai-hive/issues/172)) ([a90c202](https://github.com/werkrbee/ai-hive/commit/a90c2020828cb9af8ed9ba721df3d57adbdfc654))
* **agents-hive:** deploy hosted Barry beside Patricia ([#181](https://github.com/werkrbee/ai-hive/issues/181)) ([fc85789](https://github.com/werkrbee/ai-hive/commit/fc85789d15c4c209cb46f0a97ebff0edab770d4d))
* **agents-hive:** map a caller's tools to approval-policy actions ([#168](https://github.com/werkrbee/ai-hive/issues/168)) ([ee82a26](https://github.com/werkrbee/ai-hive/commit/ee82a26c31bd77fb13521abfb3eaa7ab9bcccb44)), closes [#116](https://github.com/werkrbee/ai-hive/issues/116)
* **agents-hive:** run the orchestration eval and choose Claude Sonnet 5.5 for Barry ([#178](https://github.com/werkrbee/ai-hive/issues/178)) ([64c2b46](https://github.com/werkrbee/ai-hive/commit/64c2b46ea10a3784b5d3e162e8535c0892387824))
* **agents-hive:** support tool calls in the model clients ([#167](https://github.com/werkrbee/ai-hive/issues/167)) ([f389239](https://github.com/werkrbee/ai-hive/commit/f389239288a6c98aa1dd42d61c9891f3fda879ef)), closes [#115](https://github.com/werkrbee/ai-hive/issues/115)


### Bug fixes

* **agents-hive:** anchor the eval's attack claim and read its fact sources ([#175](https://github.com/werkrbee/ai-hive/issues/175)) ([2b7de5d](https://github.com/werkrbee/ai-hive/commit/2b7de5d316a88d5345a89926d9e62529131a8125)), closes [#119](https://github.com/werkrbee/ai-hive/issues/119)
* **agents-hive:** let Barry wait out an MCP server's cold start ([#189](https://github.com/werkrbee/ai-hive/issues/189)) ([469bae3](https://github.com/werkrbee/ai-hive/commit/469bae3bfe3f02718eaa2aa6da11c4ec26eb9c03)), closes [#188](https://github.com/werkrbee/ai-hive/issues/188)
* **agents-hive:** let entra.sh make an API app with no callers ([#186](https://github.com/werkrbee/ai-hive/issues/186)) ([98a11d2](https://github.com/werkrbee/ai-hive/commit/98a11d2bdcc0624acfb9f6300d68e80dec4b4ad1)), closes [#120](https://github.com/werkrbee/ai-hive/issues/120)
* **agents-hive:** quote the attack's report and finish the eval README's rewrap ([#176](https://github.com/werkrbee/ai-hive/issues/176)) ([3b0c4b1](https://github.com/werkrbee/ai-hive/commit/3b0c4b15bf37132b55a7f09475d53feb58bc2251)), closes [#119](https://github.com/werkrbee/ai-hive/issues/119)
* **agents-hive:** retry a model turn the provider rate-limits instead of failing the run ([#180](https://github.com/werkrbee/ai-hive/issues/180)) ([8396204](https://github.com/werkrbee/ai-hive/commit/8396204ab49b09537a6ef97ffd1461b94d0205a0)), closes [#177](https://github.com/werkrbee/ai-hive/issues/177)
* **agents-hive:** tighten the orchestration eval's scoring ([#174](https://github.com/werkrbee/ai-hive/issues/174)) ([28827ff](https://github.com/werkrbee/ai-hive/commit/28827ff3287226394fec56b22cd855aea47ec695)), closes [#119](https://github.com/werkrbee/ai-hive/issues/119)

## [0.8.0](https://github.com/werkrbee/ai-hive/compare/v0.7.0...v0.8.0) (2026-10-29)


### Features

* **agents-hive:** add adversarial cases to trust evaluations ([#154](https://github.com/werkrbee/ai-hive/issues/154)) ([cccb3fb](https://github.com/werkrbee/ai-hive/commit/cccb3fbfbce49717cec71827118e1fbb86130511)), closes [#139](https://github.com/werkrbee/ai-hive/issues/139)
* **agents-hive:** hold promotion on repeated not-run evaluations ([#157](https://github.com/werkrbee/ai-hive/issues/157)) ([6659192](https://github.com/werkrbee/ai-hive/commit/6659192f61e4d9133790e0aba62dc579d9991174)), closes [#153](https://github.com/werkrbee/ai-hive/issues/153)
* **agents-hive:** pin each eval suite in its passport ([#156](https://github.com/werkrbee/ai-hive/issues/156)) ([230a74b](https://github.com/werkrbee/ai-hive/commit/230a74b0db9da583bbc1695232f64478f3debb6a)), closes [#149](https://github.com/werkrbee/ai-hive/issues/149)
* **agents-hive:** put hosted Patricia under the assurance loop ([#165](https://github.com/werkrbee/ai-hive/issues/165)) ([77e243f](https://github.com/werkrbee/ai-hive/commit/77e243f6c64111de89df7b8009f6994c791c5cce))
* bound sub-agents and clones ([#162](https://github.com/werkrbee/ai-hive/issues/162)) ([92092bb](https://github.com/werkrbee/ai-hive/commit/92092bb8b374b29e16926057d59df2aa4b2b342e)), closes [#130](https://github.com/werkrbee/ai-hive/issues/130)
* roll back a run or an agent's passport version ([#160](https://github.com/werkrbee/ai-hive/issues/160)) ([0e7050a](https://github.com/werkrbee/ai-hive/commit/0e7050aa2ad08c2b61673c6c1ba83b5f1c93c5f3)), closes [#128](https://github.com/werkrbee/ai-hive/issues/128)


### Bug fixes

* **agents-hive:** count provider errors in an eval as not run, not missed ([#151](https://github.com/werkrbee/ai-hive/issues/151)) ([959d542](https://github.com/werkrbee/ai-hive/commit/959d5421dc15718414d70d069e442149d87dd65b)), closes [#150](https://github.com/werkrbee/ai-hive/issues/150)


### Documentation

* list the trust evaluation follow-ups in the P2.1 plan ([#155](https://github.com/werkrbee/ai-hive/issues/155)) ([1094083](https://github.com/werkrbee/ai-hive/commit/1094083b159c86e1ff50be4e815ea75ef4c5c83a)), closes [#122](https://github.com/werkrbee/ai-hive/issues/122)
* mark rollback done in the P2.1 plan ([#161](https://github.com/werkrbee/ai-hive/issues/161)) ([9a53f00](https://github.com/werkrbee/ai-hive/commit/9a53f003ccb433b08d72a7ad46a6beea82cac4c9))
* mark sub-agent boundaries done in the P2.1 plan ([#164](https://github.com/werkrbee/ai-hive/issues/164)) ([fb3d19a](https://github.com/werkrbee/ai-hive/commit/fb3d19adb31158665d5dd71d443458b54e4f2718)), closes [#130](https://github.com/werkrbee/ai-hive/issues/130)
* mark the trust evaluation follow-ups done ([#159](https://github.com/werkrbee/ai-hive/issues/159)) ([db0a789](https://github.com/werkrbee/ai-hive/commit/db0a7892d82cd77ff2eb6b8fc58fe74c298db63c))
* set ai-hive's vision and mission ([#158](https://github.com/werkrbee/ai-hive/issues/158)) ([9796a12](https://github.com/werkrbee/ai-hive/commit/9796a12c218aa5e725b7f6e6161294d301310fbc))

## [0.7.0](https://github.com/werkrbee/ai-hive/compare/v0.6.2...v0.7.0) (2026-10-27)


### Features

* **agents-hive:** evaluate trust and catch drift ([#137](https://github.com/werkrbee/ai-hive/issues/137)) ([ac7c3be](https://github.com/werkrbee/ai-hive/commit/ac7c3be26e11269c8d3a1cab9370ef8c0796f768)), closes [#127](https://github.com/werkrbee/ai-hive/issues/127)
* **agents-hive:** give every agent a passport ([#134](https://github.com/werkrbee/ai-hive/issues/134)) ([73f7404](https://github.com/werkrbee/ai-hive/commit/73f74041069427431b141aabe9216469765ff412)), closes [#125](https://github.com/werkrbee/ai-hive/issues/125)
* **agents-hive:** record Patricia's baseline on her current pins ([#138](https://github.com/werkrbee/ai-hive/issues/138)) ([e6b0cf3](https://github.com/werkrbee/ai-hive/commit/e6b0cf38c02497f65a2915b7b4c14c7e9a22e883)), closes [#127](https://github.com/werkrbee/ai-hive/issues/127)
* **knowledge-hive:** keep a tamper-evident audit log ([#135](https://github.com/werkrbee/ai-hive/issues/135)) ([f67f45a](https://github.com/werkrbee/ai-hive/commit/f67f45a722bfef01c5db3f8017f27fdb40139c30)), closes [#126](https://github.com/werkrbee/ai-hive/issues/126)
* **workflows-hive:** add a human review queue ([#136](https://github.com/werkrbee/ai-hive/issues/136)) ([222b801](https://github.com/werkrbee/ai-hive/commit/222b801876aa3c8b41f8198b52d1abdf98765b55)), closes [#129](https://github.com/werkrbee/ai-hive/issues/129)
* **workflows-hive:** decide a step's approval from the approval policy ([#112](https://github.com/werkrbee/ai-hive/issues/112)) ([31bb188](https://github.com/werkrbee/ai-hive/commit/31bb1889d7164638ff2369dab57ed0b819d47087))
* **workflows-hive:** let a run grow and keep model turns ([#121](https://github.com/werkrbee/ai-hive/issues/121)) ([b86b24b](https://github.com/werkrbee/ai-hive/commit/b86b24b54041360fa4e6a1bf8777b3c62c831917))
* **workflows-hive:** pause a run for approval before a step ([#109](https://github.com/werkrbee/ai-hive/issues/109)) ([df1a31b](https://github.com/werkrbee/ai-hive/commit/df1a31bae4c9f288d46370f400c46a3fc36ebbde))
* **workflows-hive:** stop a step that would exceed its budget ([#110](https://github.com/werkrbee/ai-hive/issues/110)) ([4151674](https://github.com/werkrbee/ai-hive/commit/41516746d2ce25500ac72733d578166fb1a03c54))


### Documentation

* add defensive co-scaling to the vision and roadmap ([#131](https://github.com/werkrbee/ai-hive/issues/131)) ([9833929](https://github.com/werkrbee/ai-hive/commit/98339291ae8548192c0413e47bd0e478bf89d2a3)), closes [#123](https://github.com/werkrbee/ai-hive/issues/123)
* **agents-hive:** design hosted Barry over A2A ([#113](https://github.com/werkrbee/ai-hive/issues/113)) ([dc34ed3](https://github.com/werkrbee/ai-hive/commit/dc34ed34bfaed94c6eb24cc9f7702a999111a63a))
* design the agent passport and assurance loop ([#132](https://github.com/werkrbee/ai-hive/issues/132)) ([0c2cee0](https://github.com/werkrbee/ai-hive/commit/0c2cee0848936d0226feca263a4a9a6a7f1440c0)), closes [#124](https://github.com/werkrbee/ai-hive/issues/124)
* fold the frontier ecosystem gaps into the roadmap ([#148](https://github.com/werkrbee/ai-hive/issues/148)) ([3a15c42](https://github.com/werkrbee/ai-hive/commit/3a15c42d473d37c34f42129336cf0f7cf46285f8)), closes [#141](https://github.com/werkrbee/ai-hive/issues/141)
* mark Barry's approval and budget steps done in ROADMAP.md ([#111](https://github.com/werkrbee/ai-hive/issues/111)) ([4faec6e](https://github.com/werkrbee/ai-hive/commit/4faec6e72436f55bcca36cdd6b6431e18166965e))
* plan Barry's runtime and hosted Barry in ROADMAP.md ([#107](https://github.com/werkrbee/ai-hive/issues/107)) ([9d720c3](https://github.com/werkrbee/ai-hive/commit/9d720c3ce87253e0343a1c9cbad5cd7171d000e7))

## [0.6.2](https://github.com/werkrbee/ai-hive/compare/v0.6.1...v0.6.2) (2026-10-23)


### Documentation

* bring the roadmap and docs up to date with 0.6.1, and mark hosted Patricia done ([#99](https://github.com/werkrbee/ai-hive/issues/99)) ([f540868](https://github.com/werkrbee/ai-hive/commit/f540868dc58fa6ed3e9e2a3295fa4fbb6cb766be))

## [0.6.1](https://github.com/werkrbee/ai-hive/compare/v0.6.0...v0.6.1) (2026-10-23)


### Bug fixes

* **agents-hive:** stop deploy.sh when a what-if fails, and record Patricia's move to Claude ([#98](https://github.com/werkrbee/ai-hive/issues/98)) ([fe04f3c](https://github.com/werkrbee/ai-hive/commit/fe04f3cd061ccf520737a3689ccb640aabf8e8f0))


### Documentation

* **agents-hive:** record Claude on Foundry's Messages API as verified live ([#95](https://github.com/werkrbee/ai-hive/issues/95)) ([4ffb36a](https://github.com/werkrbee/ai-hive/commit/4ffb36ace70f29ded970c5b83ef685a528ea4ce1))
* **agents-hive:** record the Claude comparison and choose Claude Sonnet 5.5 for Patricia ([#97](https://github.com/werkrbee/ai-hive/issues/97)) ([cb4feae](https://github.com/werkrbee/ai-hive/commit/cb4feae1ddd63ff6653bff6300746fe2493c11b9))

## [0.6.0](https://github.com/werkrbee/ai-hive/compare/v0.5.0...v0.6.0) (2026-10-18)


### Features

* **agents-hive:** let the A2A server call any generally available Foundry model ([#84](https://github.com/werkrbee/ai-hive/issues/84)) ([0e74d0c](https://github.com/werkrbee/ai-hive/commit/0e74d0cc84226367a93424c34c6c268a1810cd4c)), closes [#77](https://github.com/werkrbee/ai-hive/issues/77)
* **agents-hive:** look up Foundry models' list prices with prices.sh ([#89](https://github.com/werkrbee/ai-hive/issues/89)) ([11c05b7](https://github.com/werkrbee/ai-hive/commit/11c05b7165555766974642819e5f14eff88490d4)), closes [#88](https://github.com/werkrbee/ai-hive/issues/88)
* **agents-hive:** record the model's publisher in the usage ledger alongside its API ([#90](https://github.com/werkrbee/ai-hive/issues/90)) ([6c511f2](https://github.com/werkrbee/ai-hive/commit/6c511f20946b093d842afdab4fe27a6d22df01a2)), closes [#85](https://github.com/werkrbee/ai-hive/issues/85)
* **agents-hive:** show each model's API at deploy.sh's gate ([#92](https://github.com/werkrbee/ai-hive/issues/92)) ([722f157](https://github.com/werkrbee/ai-hive/commit/722f15749a2288c042dee2feb586c2d8b25489c4)), closes [#87](https://github.com/werkrbee/ai-hive/issues/87)


### Bug fixes

* **agents-hive:** match deploy.sh's catalog check to the account kind main.bicep deploys ([#91](https://github.com/werkrbee/ai-hive/issues/91)) ([2fdac90](https://github.com/werkrbee/ai-hive/commit/2fdac9033887be5ebbb87c45bdf237d62d73557f)), closes [#86](https://github.com/werkrbee/ai-hive/issues/86)
* **agents-hive:** narrow the Foundry role for hosted Patricia's identity ([#82](https://github.com/werkrbee/ai-hive/issues/82)) ([936ef7e](https://github.com/werkrbee/ai-hive/commit/936ef7e02922423e1feb24dfed33ec0e20893278)), closes [#69](https://github.com/werkrbee/ai-hive/issues/69)
* **agents-hive:** refuse a modelDeployment that names no model, and apply review notes ([#94](https://github.com/werkrbee/ai-hive/issues/94)) ([a4e316c](https://github.com/werkrbee/ai-hive/commit/a4e316ce243542617dc8a566ed44fdbf50019daf))

## [0.5.0](https://github.com/werkrbee/ai-hive/compare/v0.4.0...v0.5.0) (2026-10-14)


### Features

* **agents-hive:** check built-in role ids before deploy.sh's what-if ([#81](https://github.com/werkrbee/ai-hive/issues/81)) ([57d5607](https://github.com/werkrbee/ai-hive/commit/57d5607380fe0fa97cef1fcb205c452d10d63dc5)), closes [#79](https://github.com/werkrbee/ai-hive/issues/79)
* **agents-hive:** show entra.sh's create-or-reuse plan before asking ([#74](https://github.com/werkrbee/ai-hive/issues/74)) ([1786b70](https://github.com/werkrbee/ai-hive/commit/1786b7055dc63629c275dbc87327588dcde16a1a)), closes [#68](https://github.com/werkrbee/ai-hive/issues/68)


### Bug fixes

* **agents-hive:** make entra.sh work against a real tenant ([#75](https://github.com/werkrbee/ai-hive/issues/75)) ([7ac6f04](https://github.com/werkrbee/ai-hive/commit/7ac6f0412388f3ec8e8e4f15fc3220b315c646d4)), closes [#55](https://github.com/werkrbee/ai-hive/issues/55)
* **agents-hive:** pass model provider data to Foundry deployments ([#76](https://github.com/werkrbee/ai-hive/issues/76)) ([78b31c4](https://github.com/werkrbee/ai-hive/commit/78b31c4b3c0a65fb572da0eb4992822103bcd743)), closes [#55](https://github.com/werkrbee/ai-hive/issues/55)
* **agents-hive:** use the real AcrPull role id ([#78](https://github.com/werkrbee/ai-hive/issues/78)) ([ef5cb6c](https://github.com/werkrbee/ai-hive/commit/ef5cb6c9b0b9c6530df7cbb995e262188ff425f5)), closes [#55](https://github.com/werkrbee/ai-hive/issues/55)


### Documentation

* **agents-hive:** record hosted Patricia's first deploy and GPT-5.4 eval ([#80](https://github.com/werkrbee/ai-hive/issues/80)) ([a730d34](https://github.com/werkrbee/ai-hive/commit/a730d3490587bd867c605a7d41e0ed69acbc85b1)), closes [#55](https://github.com/werkrbee/ai-hive/issues/55)
* bring ROADMAP.md up to date after 0.4.0 ([#72](https://github.com/werkrbee/ai-hive/issues/72)) ([52fdf1d](https://github.com/werkrbee/ai-hive/commit/52fdf1d7eed5d11d1282acb4e096ca6bc920b46b)), closes [#71](https://github.com/werkrbee/ai-hive/issues/71)

## [0.4.0](https://github.com/werkrbee/ai-hive/compare/v0.3.0...v0.4.0) (2026-10-10)


### Features

* **agents-hive:** add a reference A2A server for governance-review ([#61](https://github.com/werkrbee/ai-hive/issues/61)) ([0bb7ef1](https://github.com/werkrbee/ai-hive/commit/0bb7ef1a4333328598a5e14c4ed99d0ee40fe377)), closes [#54](https://github.com/werkrbee/ai-hive/issues/54)
* **agents-hive:** deploy hosted Patricia to Azure ([#62](https://github.com/werkrbee/ai-hive/issues/62)) ([e5a81a1](https://github.com/werkrbee/ai-hive/commit/e5a81a11ac007be2b6bfbba04216868628475f6f)), closes [#55](https://github.com/werkrbee/ai-hive/issues/55)
* **agents-hive:** publish A2A Agent Cards for Barry and Patricia ([#49](https://github.com/werkrbee/ai-hive/issues/49)) ([a220660](https://github.com/werkrbee/ai-hive/commit/a22066058923b090373fe6b9b52b3fbdc0d67524)), closes [#43](https://github.com/werkrbee/ai-hive/issues/43)
* **knowledge-hive:** ship state templates and a validator ([#60](https://github.com/werkrbee/ai-hive/issues/60)) ([cb9db70](https://github.com/werkrbee/ai-hive/commit/cb9db70250131159ee274b4b6f8c7d49faca080b)), closes [#46](https://github.com/werkrbee/ai-hive/issues/46)
* **rules-hive:** define a structured approval/mandate policy ([#58](https://github.com/werkrbee/ai-hive/issues/58)) ([02038d9](https://github.com/werkrbee/ai-hive/commit/02038d9a01cc79bbd238484ed3e5d1a7224c4d75)), closes [#44](https://github.com/werkrbee/ai-hive/issues/44)


### Documentation

* add a product adoption guide ([#63](https://github.com/werkrbee/ai-hive/issues/63)) ([c2e9bb1](https://github.com/werkrbee/ai-hive/commit/c2e9bb1e0620fdf7ccc297806df7a956e9600233)), closes [#56](https://github.com/werkrbee/ai-hive/issues/56)
* add hosted A2A agents and P1 docs work to the roadmap ([#50](https://github.com/werkrbee/ai-hive/issues/50)) ([92f128a](https://github.com/werkrbee/ai-hive/commit/92f128ac89331765a0dfe23c833fb67555071dbd)), closes [#48](https://github.com/werkrbee/ai-hive/issues/48)
* **knowledge-hive:** create the hive and its design note ([#59](https://github.com/werkrbee/ai-hive/issues/59)) ([900557b](https://github.com/werkrbee/ai-hive/commit/900557b93c0bd6f085ea618881d77cc596c6fb05)), closes [#45](https://github.com/werkrbee/ai-hive/issues/45)
* mark the finished P1 items in ROADMAP.md ([#70](https://github.com/werkrbee/ai-hive/issues/70)) ([6c1e820](https://github.com/werkrbee/ai-hive/commit/6c1e820fb1f5dc303f8ae15ea12f980f46c1e3ff)), closes [#67](https://github.com/werkrbee/ai-hive/issues/67)
* reconcile the repo with workflows-hive and knowledge-hive ([#64](https://github.com/werkrbee/ai-hive/issues/64)) ([da0ae87](https://github.com/werkrbee/ai-hive/commit/da0ae87b4a418bf2f01bcbf1c8851c2a074a210a)), closes [#48](https://github.com/werkrbee/ai-hive/issues/48)

## [0.3.0](https://github.com/werkrbee/ai-hive/compare/v0.2.0...v0.3.0) (2026-10-08)


### Features

* **agents-hive:** define the execution-contract schema ([#40](https://github.com/werkrbee/ai-hive/issues/40)) ([a53e945](https://github.com/werkrbee/ai-hive/commit/a53e9452f84aceb87ed1b9a4fa5bed9ad3b55032)), closes [#7](https://github.com/werkrbee/ai-hive/issues/7)
* **mcp-hive:** resolve remote servers from their Server Cards ([#42](https://github.com/werkrbee/ai-hive/issues/42)) ([9d4ac6e](https://github.com/werkrbee/ai-hive/commit/9d4ac6ecaa80a453e3e4551699afda460afe0c4a)), closes [#9](https://github.com/werkrbee/ai-hive/issues/9)

## [0.2.0](https://github.com/werkrbee/ai-hive/compare/v0.1.1...v0.2.0) (2026-10-08)


### Features

* **workflows-hive:** add a resumable two-step workflow spike ([#37](https://github.com/werkrbee/ai-hive/issues/37)) ([45c10a2](https://github.com/werkrbee/ai-hive/commit/45c10a2787358abcf2d09f600f1791bc14fc3cbc)), closes [#11](https://github.com/werkrbee/ai-hive/issues/11)


### Documentation

* add the P0 sprint file ([#33](https://github.com/werkrbee/ai-hive/issues/33)) ([b44e997](https://github.com/werkrbee/ai-hive/commit/b44e9976c6534a48b3e5da549c1a5674cb3d0a32)), closes [#32](https://github.com/werkrbee/ai-hive/issues/32)
* **mcp-hive:** target the 2026-07-28 MCP spec ([#35](https://github.com/werkrbee/ai-hive/issues/35)) ([64142ca](https://github.com/werkrbee/ai-hive/commit/64142cac3362d5440be015df8d35f5680bdbb3e3)), closes [#8](https://github.com/werkrbee/ai-hive/issues/8)
* **workflows-hive:** add the hive and its design note ([#36](https://github.com/werkrbee/ai-hive/issues/36)) ([82ecb94](https://github.com/werkrbee/ai-hive/commit/82ecb948592d64ee2e96e47541523e63f03a3447)), closes [#10](https://github.com/werkrbee/ai-hive/issues/10)

## [0.1.1](https://github.com/werkrbee/ai-hive/compare/v0.1.0...v0.1.1) (2026-10-07)


### Bug fixes

* **plugins-hive:** update installer help and error text for the monorepo ([#30](https://github.com/werkrbee/ai-hive/issues/30)) ([0a2b1b3](https://github.com/werkrbee/ai-hive/commit/0a2b1b33c293c97cf1344d88b7b939d7911dfc2d)), closes [#29](https://github.com/werkrbee/ai-hive/issues/29)


### Documentation

* describe monorepo setup in README and close out Sprint 0 checklist ([#26](https://github.com/werkrbee/ai-hive/issues/26)) ([06dce9b](https://github.com/werkrbee/ai-hive/commit/06dce9b0b96c10685d461e5d2f7b3c00a8567759)), closes [#13](https://github.com/werkrbee/ai-hive/issues/13)
* finalize community health files and CODEOWNERS ([#21](https://github.com/werkrbee/ai-hive/issues/21)) ([6c5ce9d](https://github.com/werkrbee/ai-hive/commit/6c5ce9dfabddc9e558334ce138c193d0ff341c4f)), closes [#2](https://github.com/werkrbee/ai-hive/issues/2)
* **hives:** replace submodule wording in plugins-hive and projects-hive ([#25](https://github.com/werkrbee/ai-hive/issues/25)) ([534b8de](https://github.com/werkrbee/ai-hive/commit/534b8de8ca32056e0ab21f873362571b4af83429)), closes [#14](https://github.com/werkrbee/ai-hive/issues/14)
* point every hive link at ai-hive and record archiving the standalone repos ([#28](https://github.com/werkrbee/ai-hive/issues/28)) ([1a51fad](https://github.com/werkrbee/ai-hive/commit/1a51fad1cdb5cae4bb26b382446e835b63435418)), closes [#23](https://github.com/werkrbee/ai-hive/issues/23)
* **skills-hive:** remove the Cursor Remote Rule install option ([#31](https://github.com/werkrbee/ai-hive/issues/31)) ([e31f18a](https://github.com/werkrbee/ai-hive/commit/e31f18a5b33d371ebd4b97866f939ad346e22ca7)), closes [#27](https://github.com/werkrbee/ai-hive/issues/27)


### CI

* parse PowerShell installers with the PowerShell parser ([#24](https://github.com/werkrbee/ai-hive/issues/24)) ([2b25c92](https://github.com/werkrbee/ai-hive/commit/2b25c924430ace6abf2b3075cde202bb0fa68a41)), closes [#16](https://github.com/werkrbee/ai-hive/issues/16)

## 0.1.0 (2026-10-07)


### Refactoring

* consolidate hives into monorepo ([#15](https://github.com/werkrbee/ai-hive/issues/15)) ([65f91bf](https://github.com/werkrbee/ai-hive/commit/65f91bfef8b6ff6042a2889f3adc7f288067fe25)), closes [#1](https://github.com/werkrbee/ai-hive/issues/1)


### CI

* add release-please for SemVer tags, changelog, and GitHub Releases ([#18](https://github.com/werkrbee/ai-hive/issues/18)) ([05ba579](https://github.com/werkrbee/ai-hive/commit/05ba5791bae1a49a6ad03c4d0161032aebe7057b)), closes [#5](https://github.com/werkrbee/ai-hive/issues/5)
* run real installer checks and fail on empty artifact sets ([#17](https://github.com/werkrbee/ai-hive/issues/17)) ([cd2d7f6](https://github.com/werkrbee/ai-hive/commit/cd2d7f68bf0bf3a33b244aa0bab732225636832c))
