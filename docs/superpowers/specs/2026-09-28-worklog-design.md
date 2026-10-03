# worklog 設計書

Claude Code と Codex のログから、プロジェクトごとの稼働時間と作業内容をターミナルで確認する CLI `worklog` を作る。稼働時間はバーで表示し、CSV で出力する。作業内容の要約は、CLI が出す素材を skill から呼んだ Claude が文章にする。

用途は自分の振り返りと、稼働報告・請求の根拠の両方。数え方のルールをレポートに明示し、手で補正できるようにする。

## 前提

| 項目 | 内容 |
|---|---|
| 対象ログ | Claude Code(`~/.claude/projects/**/*.jsonl`、サブエージェントの `subagents/*.jsonl` を含む)と Codex(`~/.codex/sessions/**/*.jsonl`) |
| 対象外 | Codex の旧形式ログ(2025 年 8 月ごろまで。各行に時刻と cwd が無い) |
| 実行環境 | Python 3.11 以上(`tomllib` を使う)。実行時の依存は標準ライブラリだけ。テストは pytest |
| 導入 | `uv tool install git+https://github.com/Kyo1M/claude-worklog` で `worklog` コマンドを入れる(改造するときは clone して `--editable`) |
| 公開 | GitHub で公開する。コードと既定値に個人のパス・案件名を入れない(個人の設定は `~/.config/worklog/` に置く) |

測れるのは「AI とやりとりしていた時間」で、実際の作業時間の下限にあたる。会議・資料の読み込み・AI を使わない作業は含まれない。この注記はレポートの末尾にも出す。会議は、議事録の frontmatter に開始・終了時刻があるものだけ稼働に足す(「議事録の会議」の節)。

## 全体の流れ

```
~/.claude/projects/**/*.jsonl ─┐
                                ├─ ingest ─→ SQLite(~/.local/share/worklog/worklog.db)
~/.codex/sessions/**/*.jsonl ───┘               │
                                                 ├─ day / week / month(バー表示)
config.toml(名寄せ・案件・しきい値)──────────────┼─ export(CSV)
adjustments.csv(手での補正)──────────────────────┼─ material(要約の素材)
                                                 └─ projects(判定結果の点検)
```

レポート系のコマンドは、実行時に未取り込みの差分を自動で取り込む(`--no-ingest` で省略)。

## 稼働時間の数え方

1. ログの 1 行ごとの時刻を、UTC の「分」(1 分単位)に丸める
2. 集計単位(既定はプロジェクト。`--by repo` でリポジトリ、`--by client` で案件)ごとに、Claude・Codex・サブエージェント・並行セッションの区別なく分を 1 本の時間軸に合成する。同じ分は 1 回だけ数える
3. イベントがあった分を稼働とする。単発のイベントも 1 分になる
4. 隣り合うイベントの分の差が `gap_minutes`(既定 15)以下なら、その間の分もすべて稼働とする。差が 16 分以上なら区切る
   - 例: 10:00 と 10:15 → 10:00〜10:15 の 16 分。10:00 と 10:16 → 2 分
5. 稼働した分を、設定したタイムゾーン(既定はシステムのローカル)の日付に振り分ける。0 時をまたぐ区間は日ごとに分かれる
6. 集計単位が違えば、同じ時刻でもそれぞれに数える。並行して進めたプロジェクトの合計は 24 時間を超えることがある(仕様)。レポートの合計欄には、各単位の合計と、全体を 1 本の時間軸に合成した実時間を並べて出す
7. 議事録の会議の時間(開始〜終了の各分)を、議事録があるリポジトリの集計単位の時間軸に加える。AI の稼働と同じ分は 1 回だけ数え、しきい値ではつなげない
8. 補正ファイルの分を日・プロジェクト単位で加減する(`--raw` で補正前)

数えるログの行は次のとおり。

| ソース | 数える行 |
|---|---|
| Claude Code | `type` が `user`・`assistant`・`system`・`queue-operation` で `timestamp` を持つ行。cwd が分かる前の行(先頭の `queue-operation`)は直後の行と同じ分なので数えない |
| Codex | `timestamp` を持つすべての行(新形式) |

自動実行は既定では数えない(`include_automated = true` で数える)。Claude Code は `entrypoint` が `sdk` で始まるセッション(`claude -p`・Agent SDK)、Codex は `session_meta.source` が `exec` のセッションを自動実行とする。同じ分・同じ cwd に対話のセッションがあれば、その分は対話として数える。Codex のサブエージェント(`source` が `{"subagent": ...}`。承認の審査など)は時間を数え、セッションとしては `material` に並べない。

## リポジトリ・プロジェクト・案件の判定

cwd ごとに、レポートを出す時点で次の順に判定する(設定を直せば過去分にも反映される)。

1. `[aliases]` で cwd を書き換える(旧パス → 現在のパス。前方一致で、書き換えが止まるまで繰り返す。同じ別名は 1 回だけ使う)
2. cwd から親へたどり、`.git` があるディレクトリをリポジトリとする。パスが残っていなくても、祖先の `.git` の有無で判定する
3. `.git` がファイル(git worktree)なら、`gitdir:` が指す本体のリポジトリに寄せる。本体が旧パスなら `[aliases]` を当ててたどり直す
4. git リポジトリが見つからないときは、`roots` に書いたディレクトリの直下のフォルダをプロジェクトとみなす(git の無いフォルダ・消えた旧プロジェクト用)
5. それでも当たらない cwd(`/`、`~` など)は「(未分類)」とし、レポートに出す
6. リポジトリを `[projects]` のパターン(上から順に最初に当たったもの)でプロジェクトに束ねる。当たらなければリポジトリ名を 1 つのプロジェクトとする
7. リポジトリを `[clients]` のパターン(上から順に最初に当たったもの)で案件に寄せる。当たらなければ「(案件未設定)」

案件はプロジェクト単位で決める。束ねたリポジトリで案件が分かれたときは `[clients]` の上にあるものを採る。

リポジトリの表示名はディレクトリ名。同じ名前が複数あるときは「親ディレクトリ名/名前」にする。

## 保存形式(SQLite)

| テーブル | 列 | 一意キー | 用途 |
|---|---|---|---|
| `activity` | `minute`(UTC の epoch 分)、`source`、`cwd` | 全列 | 稼働時間の計算 |
| `sessions` | `source`、`session_id`、`title`、`cwd`、`first_minute`、`last_minute` | `source, session_id` | 要約の素材 |
| `prompts` | `source`、`session_id`、`minute`、`cwd`、`text`(500 字まで) | `source, session_id, minute, text` | 要約の素材 |
| `files` | `path`、`size`、`offset` | `path` | 差分の取り込み |

- 分と cwd の組で保存するので、同じイベントを二度読んでも結果は変わらない(再開したセッションが履歴を複製していても二重に数えない)
- `files` に読み込み済みの位置を持ち、次回は増えた分(改行で終わる完全な行)だけを読む。ファイルが前回より小さければ最初から読み直す
- Codex の依頼文は `event_msg` の `user_message` と、`item_completed` の `UserMessage` から読む。IDE の拡張などが付ける前置きは `## My request for Codex:` より後ろだけを残す
- 依頼文として保存するのは人が入力した文だけ。ツールの結果・`isMeta`・サブエージェント内の依頼・`<` で始まる自動挿入の文・`/clear` などの組み込みコマンドは除く。スラッシュコマンドは「コマンド名 引数」の形で残す。`material` では同じセッション内の同じ依頼文を 1 件にまとめる
- タイトルは Claude が `ai-title` 行の `aiTitle`、Codex が `~/.codex/session_index.jsonl` の `thread_name`

## コマンド

| コマンド | 内容 |
|---|---|
| `worklog day [YYYY-MM-DD]` | 1 日のプロジェクト別の稼働バーと、時間帯のタイムライン(30 分刻み)。省略時は今日 |
| `worklog week [YYYY-MM-DD]` | その日を含む週(月曜始まり)。日別の積み上げバーとプロジェクト別の合計 |
| `worklog month [YYYY-MM]` | 月の週別の積み上げバーとプロジェクト別の合計 |
| `worklog export --from --to [--grain day\|week\|month]` | 縦持ちの CSV(`period,client,project,repo,minutes,hours`。`repo` は `--by repo` のときだけ埋める)を標準出力へ |
| `worklog material [--date \| --from --to] [--project] [--max-prompts N] [--prompt-chars N] [--json]` | プロジェクトごとの稼働時間・セッション(時刻・ソース・タイトル・依頼文)・期間内の自分のコミット。1 か月分は依頼文を絞って Markdown で約 5 万字 |
| `worklog projects [--from --to]` | 案件 / プロジェクト / リポジトリ / cwd の判定結果と分数。名寄せ設定の点検用 |
| `worklog ingest` | 取り込みだけを行い、読んだファイル数・行数・読み飛ばした行数を出す |
| `worklog config [--init]` | 設定ファイルの場所と有効な設定を表示。`--init` でひな形を書き出す |

共通オプション: `--by project|repo|client`(既定 project)、`--raw`(補正なし)、`--no-ingest`、`--no-color`。

`--project <名前>`(day・week・month・export・material): プロジェクト名かリポジトリ名が一致するイベント・会議・補正だけで集計する。day・week・month では、日ごとに稼働した分を連続した範囲にまとめた開始〜終了の一覧を末尾に出す(複数の集計単位は 1 本の時間軸に合成し、日をまたぐ範囲は 0 時で分ける。補正は分の位置を持たないので一覧に含めない)。

### 表示

- バーは最大値を基準に幅をそろえる。名前の列は表示幅(`unicodedata.east_asian_width`)で桁をそろえ、長い名前は表示幅で切り詰める
- 積み上げバーは上位 7 件を個別に、残りを「その他」にまとめる(下のプロジェクト別の一覧は全件)
- プロジェクトごとに色を分ける。標準出力が端末でないとき・`NO_COLOR` があるとき・`--no-color` のときは色を付けない。積み上げバーは色が無いとき、プロジェクトごとに塗りの文字を変える
- 見出しに期間・しきい値を、末尾に「AI とやりとりしていた時間の推定で、会議などは含まない」旨を出す

```
2026-09-28 (月)  しきい値 15 分・1 分単位       合計 7h42m(実時間 6h55m)
client-a-dashboard            ████████████████████░░░░  3h25m
blog                          ██████████░░░░░░░░░░░░░░  1h48m
(未分類)                      █░░░░░░░░░░░░░░░░░░░░░░░    10m

時間帯                        0     6     12    18    24
client-a-dashboard            ··········▇▇▇▇▇····▇▇▇·····
```

## 設定

`~/.config/worklog/config.toml`(`XDG_CONFIG_HOME` があればそちら)。無ければ既定値で動く。

```toml
timezone = "Asia/Tokyo"   # 省略時はシステムのローカル
gap_minutes = 15
include_automated = false
roots = ["~/Developer"]

[sources]
claude = "~/.claude/projects"
codex  = "~/.codex/sessions"

[aliases]
"~/Documents/Develop/*" = "~/Developer/*"

[projects]
"分析基盤" = ["~/Developer/client-a/*"]

[clients]
"案件A" = ["~/Developer/client-a/*"]
"個人"  = ["~/Developer/*"]
```

補正は `~/.config/worklog/adjustments.csv`(列 `date,project,minutes,note`。`project` はプロジェクト名かリポジトリ名、`minutes` は負も可)。保存先の DB は `~/.local/share/worklog/worklog.db`(`XDG_DATA_HOME` があればそちら)。

## 議事録の会議

議事録を作ったプロジェクトは、会議の時間もそのプロジェクトの稼働にあたる。議事録を書く作業は Claude Code のセッションとして数えられるが、会議そのものはログに残らないため、議事録の frontmatter から足す。

```yaml
---
title: 定例
date: "2026-09-28"
start: "14:00"
end: "15:00"
---
```

- 読む場所: ログから分かったリポジトリごとに、設定 `minutes`(リポジトリからの相対 glob。既定 `["docs/minutes/**/*.md"]`、`[]` で読まない)に当たるファイル。`_` と `.` で始まるフォルダ・ファイル(`_drafts/` など)は読まない
- 読むもの: 先頭の `---` の間にある字下げの無い `date`・`start`・`end`・`title`。YAML の入れ子やリストは読まない(依存を増やさないため)
- `date` が無い・読めないファイルは議事録として扱わない。`start`・`end` が無いものは数えず、レポートの末尾に件数を出す。期間内で時刻が読めない・終了が開始より前のものは警告を出して数えない
- 時刻は設定のタイムゾーンの現地時刻として読む。0 時をまたぐ会議は扱わない
- 開始・終了時刻は meeting-minutes skill が議事録を作るときに書く。過去の議事録には書き足さない

## 要約 skill

`~/Developer/Skills/worklog/SKILL.md` に置き、`scripts/link-skills.sh` で配って README の管理表に追記する(どのリポジトリからも使うため)。

- 起動例: 「今週の稼働を見せて」「9 月の稼働と作業内容をまとめて」「/worklog」
- 手順
  1. 期間に合う `worklog day|week|month` を実行して、バーをそのまま見せる
  2. `worklog material --json` を読み、プロジェクトごとに作業内容を 3〜5 行で要約する
  3. 案件単位の依頼なら `--by client` の数字と要約で稼働報告の下書きを作る
- 公開版のリポジトリにも同じ `SKILL.md` を `skill/worklog/` として同梱する(正本は `~/Developer/Skills/worklog/`)

## エラー処理

- 壊れた JSON の行は読み飛ばし、`ingest` の結果に件数を出す
- ソースのディレクトリが片方だけ無いときは、黙ってもう一方だけで続ける(Claude Code だけ・Codex だけの人がいるため)。両方無いときだけ警告する
- 取り込み方を変えたら DB の `user_version` を上げる。上がった DB は、次の取り込みで手元に残っているログを最初から読み直す
- 補正ファイル・設定ファイルの書式の誤りは、行番号付きで示して終了する(補正ファイルは BOM 付きの UTF-8 も読む)
- `git log` が失敗したリポジトリは、コミットを空にして続ける

## モジュール構成

| ファイル | 役割 |
|---|---|
| `src/worklog/config.py` | 設定の読み込み・既定値・パスの展開 |
| `src/worklog/sources/claude.py`、`codex.py` | 1 行を解析し、稼働の分・依頼文・セッション情報を返す |
| `src/worklog/store.py` | SQLite の作成・保存・読み出し |
| `src/worklog/ingest.py` | ファイルの差分読み込み |
| `src/worklog/resolve.py` | cwd → プロジェクト → 案件 |
| `src/worklog/activity.py` | 分の合成・しきい値でのつなぎ・日への振り分け |
| `src/worklog/report.py` | 期間ごとの集計と補正の反映 |
| `src/worklog/meetings.py` | 議事録の frontmatter から会議の時間を読む |
| `src/worklog/render.py` | バー・タイムライン・表示幅 |
| `src/worklog/material.py` | 要約の素材(git log を含む) |
| `src/worklog/cli.py` | argparse とコマンドの振り分け |

## テスト

合成した小さな jsonl をフィクスチャにする(実ログは使わない)。

- 稼働計算
  - 差 15 分はつながり、16 分は切れる
  - 単発のイベントは 1 分になる
  - 0 時をまたぐ区間は日ごとに分かれる
  - 同じプロジェクトの並行セッションは二重に数えない
  - 別のプロジェクトはそれぞれに数え、実時間は合成して数える
- プロジェクト判定: git ルート・サブディレクトリ・worktree・別名・消えたパス・(未分類)・案件の当てはめ
- 取り込み: 追記分だけ読む・途中の行は次回に回す・二度読んでも結果が同じ・小さくなったファイルは読み直す・壊れた行を数える
- 依頼文の抽出: ツールの結果・`isMeta`・サブエージェント・自動挿入を除き、スラッシュコマンドを残す
- 表示: 全角を含む名前でもバーの開始がそろう・色なしの出力
- CSV と補正: 補正ありと `--raw` の値、週・月の粒度
- 議事録の会議: AI の稼働と重なる分を二重に数えない・リポジトリの属するプロジェクトに入る・時刻の無いものは件数だけ出す・下書きと期間外を読まない

完了の確認として、実データの 9 月分で全体の実時間を出し、事前の試算(しきい値 15 分で約 72h)と近いことを見る。
