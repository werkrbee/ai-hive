# Changelog

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
