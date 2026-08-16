# ADR-0001：分離 Taiwan Core 與 AlphaMaster Research Lab

## 狀態

Accepted，2026-08-02。

## 背景

AlphaMaster 已具公式註冊、詞彙版本、VM、候選生成、研究評估及 Web 工作管理，但其主要資料、部位、成本、風險及交易假設源自 MT5、FTMO、forex 或連續多空回測。

`tw-sepa-screener` 已具台股官方來源、Point-in-time 控制、DuckDB／Parquet、公司行動、每日 pipeline、策略版本、紙上訂單／成交／NAV 及治理邊界。其當前工作樹尚未封存為 clean release。

把兩者直接合併會同時增加市場語義污染、授權、驗證和升級風險。

## 決策

採用分離架構：

- Taiwan Core 是台股資料、交易語義、帳本、策略 registry 及正式決策的 System of Record。
- AlphaMaster 是唯讀資料消費者及 `research-only` 候選產生者。
- 本治理倉庫保存契約、ADR、schema 及里程碑。
- 兩系統只透過不可變、版本化、含 hash 的資料集與候選策略封包連接。
- AlphaMaster 不持有 broker credential，也不能寫 formal strategy、orders、fills 或 NAV。

## 考慮過的替代方案

### A. Fork AlphaMaster 並全面台股化

拒絕作為第一步。需要重寫 MT5、position、cost、ledger、validation 及 live runner，會讓研究機制和台股 SoR 綁死，也擴大 AGPL 衍生與部署審查面。

### B. 把 AlphaMaster 程式碼直接合併進 `tw-sepa-screener`

拒絕。會混淆正式與研究依賴，研究 UI 或 script 可能取得正式資料庫寫入權，亦不利於回退或替換研究引擎。

### C. 分離系統，以 artifact contract 溝通

採用。可以先重用成熟機制，讓台股市場與治理邊界保持權威，並可獨立升級或停用 AlphaMaster。

## 後果

### 正面

- AlphaMaster 的市場假設不會直接污染 formal path。
- Taiwan Core 可在沒有 AlphaMaster 時繼續每日運作。
- 研究候選可完全重播、稽核、拒絕或替換。
- 權限上能禁止研究引擎自動升級及下單。
- 未來可替換模型而不重建官方資料及帳本。

### 代價

- 需要維護兩個 schema 與 adapter。
- 同一候選會在 AlphaMaster 研究代理和 Taiwan cash ledger 各評估一次。
- 需處理 feature 計算一致性及版本漂移。
- 部署 AlphaMaster Web 服務前仍需完成 AGPL 審查。

## 約束

- 禁止共享可寫 production DuckDB。
- 禁止 AlphaMaster 直接匯入正式策略檔。
- 禁止 adapter 自動猜測未知欄位或 forward-fill market state。
- 任何 schema major 變更都須新 ADR 或更新本 ADR。
- 未來若要合併 repositories，必須先證明權限、授權、回退和 OOS 邊界不會弱化。

