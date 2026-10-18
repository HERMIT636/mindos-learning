# 贡献指南

MindOS 目前是本地运行的自定义课程学习原型。欢迎提交课程规划、教学提示词、题目质量、无障碍和数据安全方面的改进。

提交代码前运行 `python -m unittest discover -s tests -v`。涉及课程推进、测验评分或记忆规则时，请说明测试场景与局限；任何掌握百分比都不能被表述为已验证的真实能力。不要提交 API 密钥、学习者数据库、私人测评题或未经许可的材料。

前端文件使用 Prettier 格式化（配置见 `.prettierrc`）：提交前对改动的 `.js/.css/.html` 运行 `npx prettier --write <文件>`；`web/vendor/` 下的第三方压缩文件保持原样，不要格式化。浏览器检查可用 `python scripts/check_browser.py <suite>` 运行。

通过 [GitHub Issues](https://github.com/HERMIT636/mindos-learning/issues) 说明问题及复现步骤，通过 Pull Request 提交修改。反馈日志中请先移除密钥与个人信息。原创项目文件按根目录 MIT 许可贡献。
