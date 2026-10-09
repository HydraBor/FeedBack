# 第三方代码与资料说明

根目录 [MIT License](LICENSE) 适用于本项目原创程序代码与说明文档。第三方代码保留原许可证；竞赛题目、平台资料和引用内容不因放入本仓库而改为 MIT。下述范围与各条数据的来源、许可字段共同使用。

## ACGO 爬虫辅助代码

- 来源：[HydraBor/ACGO-crawler](https://github.com/HydraBor/ACGO-crawler)
- 版本：`390b61d95b5aaeb245d8d2f4f993d5ce385654f9`
- 位置：`integrations/acgo/vendor/`
- 许可：MIT，原署名与许可全文见 [vendor/LICENSE](integrations/acgo/vendor/LICENSE)，来源记录见 [SOURCE.json](integrations/acgo/vendor/SOURCE.json)。

本项目的采集调度和学生材料导入流程在此基础上适配，不代表 ACGO 官方服务。ACGO、洛谷、DeepSeek 和周老师 OJ 的服务权限、接口及使用要求仍由各平台管理。

## 竞赛资料与题单

`data/public/` 是教学参考资料，包含第三方题面、候选题解、来源记录、知识标签、广东分数线核对与 AI 审核结论。原题权利归原权利人；AI 审核不改变原资料授权，也不等于官方认证。

| 资料 | 来源与许可范围 |
| --- | --- |
| CSP-J/S 真题 | 原题来源 CCF / NOI，题面交叉来源洛谷；每题的 `source`、`editorial_source`、`license` 等字段记录来源与已知范围 |
| 2025 CSP-J/S 题目 | [官方发布说明](https://www.noi.cn/zxzy/lnzl/jszl/2025-12-15/854079.shtml)标明 CC BY-NC；须遵守其署名及非商业限制，不作为 MIT 数据发布 |
| 其他年度题目与候选题解 | 保留原来源和逐题许可记录；尚未核实完整再分发许可的内容不额外授予使用权，使用前核对原权利人要求 |
| 第三方整理题解 | 来源为 [公开第二轮整理](https://www.cspfirstround.com/round2?year=2025)，部分包含模型生成内容；只作为有来源的教学参考与静态审核资料 |
| ACGO 题单元信息 | 来源 [ACGO 题单与学习导图](https://www.acgo.cn/collection)，保存标题、链接、描述及成员元信息，不保存学生数据或完整题面 |
| 广东规则与分数核对 | 保存官方公告链接及分数统计；2019 核对文件不包含获奖名单中的个人信息 |

公开仓库保留运行所需的已整理参考库和审核记录；原始抓取副本、下载的试卷 PDF 属于本地采集缓存，不随仓库上传。维护脚本可按需重新收集，仍需遵循对应来源规则。

## 依赖

Python 依赖记录在 `requirements.lock.txt`，JavaScript 依赖记录在各自 `package-lock.json`。依赖的许可证由其上游项目提供，不被根目录 MIT License 替换。仓库不分发安装后的依赖目录、Node 二进制或 Chromium。
