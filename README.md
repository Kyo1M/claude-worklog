# worklog

Claude Code と Codex のログから、プロジェクトごとの稼働時間をターミナルにバーで表示する CLI です。日・週・月の集計、複数のリポジトリを束ねたプロジェクト単位・案件(クライアント)単位の合計、CSV 出力、作業内容の要約用の素材の出力ができます。

ログはローカルで読むだけで、外部には送信しません。依存は Python の標準ライブラリだけです。

```
$ worklog day
2026-09-28 (月)  しきい値 15 分・1 分単位    合計 5h13m(実時間 5h01m)

dashboard     ████████████████████████    2h46m
side-project  █████████▉░░░░░░░░░░░░░░    1h08m
dotfiles      █████▎░░░░░░░░░░░░░░░░░░      36m
blog          ████▊░░░░░░░░░░░░░░░░░░░      33m
etl           █▌░░░░░░░░░░░░░░░░░░░░░░      10m

時間帯        0     3     6     9     12    15    18    21    24
dashboard     ····················▇▇▇▇▇▇▇·····················
side-project  ··········································▇▇▇···
dotfiles      ···················▇▇···························
blog          ····························▇▇··················
etl           ·······················▇▇·······················

※ AI とやりとりしていた時間の推定です。会議や AI を使わない作業は含みません。
```

```
$ worklog week
2026-09-21 (月) 〜 2026-09-27 (日)  しきい値 15 分・1 分単位    合計 28h11m(実時間 27h49m)

月 09/21  ███████████████████▓▓▓▓▓▒▒▒▒▒▒░             3h46m
火 09/22  ███████████████████████████▓▓▓▒▒▒▒▒▒####    4h53m
水 09/23  ███████████████▓▓▒▒░░░░░░░###               3h29m
木 09/24  ███████████▓▓▓▓▓▓▒░░░░░░░░####              3h40m
金 09/25  ██████████▓▓▓▓▓▓▓▓▓▓▓▒▒░░░░#####            3h54m
土 09/26  ██████████▓▓▓▓▓▓▓▓▓▓▓▓▒▒▒▒▒▒▒▒▒▒░░░░░░░     4h46m
日 09/27  ████████████████▓▓▒▒▒▒▒▒▒▒▒░##              3h43m

█ dashboard  ▓ blog  ▒ side-project  ░ etl  # dotfiles

プロジェクト別
dashboard     ████████████████████████   13h05m
blog          █████████▋░░░░░░░░░░░░░░    5h14m
side-project  ████████░░░░░░░░░░░░░░░░    4h21m
etl           ██████░░░░░░░░░░░░░░░░░░    3h18m
dotfiles      ████▏░░░░░░░░░░░░░░░░░░░    2h13m

※ AI とやりとりしていた時間の推定です。会議や AI を使わない作業は含みません。
```

## 必要なもの

- Python 3.11 以上
- [uv](https://docs.astral.sh/uv/)(インストールに使います)
- Claude Code(`~/.claude/projects`)または Codex(`~/.codex/sessions`)のログ

## インストール

```bash
uv tool install git+https://github.com/Kyo1M/claude-worklog
worklog config --init   # ~/.config/worklog/config.toml のひな形を作る(任意)
```

更新は `uv tool upgrade worklog` です。手元で改造するときは clone して `uv tool install --editable ./claude-worklog` で入れてください。

## 使い方

| コマンド | 内容 |
|---|---|
| `worklog` / `worklog day [YYYY-MM-DD\|yesterday]` | 1 日のプロジェクト別の稼働と時間帯のタイムライン |
| `worklog week [YYYY-MM-DD]` | その日を含む週(月曜始まり)の日別の積み上げバー |
| `worklog month [YYYY-MM]` | 月の週別の積み上げバーとプロジェクト別の合計 |
| `worklog export --from --to [--grain day\|week\|month]` | CSV(`period,client,project,repo,minutes,hours`)を標準出力へ |
| `worklog material [--date \| --from --to] [--json]` | 作業内容の要約の素材(セッションのタイトル・依頼文・期間内のコミット) |
| `worklog projects` | 作業ディレクトリがどの案件・プロジェクト・リポジトリに判定されたか |
| `worklog ingest` | ログの取り込みだけを行う |
| `worklog config [--init]` | 設定の場所と内容を表示する |

共通オプション:

- `--by project | repo | client`: 集計単位(既定はプロジェクト。リポジトリ単位・案件単位にも切り替えられる)
- `--raw`: 補正ファイルを反映しない
- `--no-ingest`: 実行前の取り込みを省く
- `--no-color`: 色を付けない

`--project <名前>`(day・week・month・export・material): プロジェクト名かリポジトリ名が一致するものだけを数えます。day・week・month では、日ごとに稼働が続いた範囲の開始〜終了の一覧も出します(しきい値以内の空白はつながった 1 つの範囲になります)。

```
$ worklog month 2026-10 --project ワクチン分析
...
開始〜終了
10/01 (木)     23m  00:00〜00:04 4m、09:11〜09:21 10m、09:39〜09:48 9m
10/02 (金)     16m  14:23〜14:27 4m、15:50〜16:02 12m
```

レポート系のコマンドは、実行のたびに新しく増えたログだけを取り込みます(2 回目以降は一瞬です)。取り込んだ結果は `~/.local/share/worklog/worklog.db` に残るので、Claude Code が古いログを削除しても過去の集計は消えません。worklog の更新で取り込み方が変わったときは、次の実行で手元に残っているログを自動で読み直します(元のログが削除済みの期間は、以前の取り込み結果のまま残ります)。

## 稼働時間の数え方

1. ログの 1 行ごとの時刻を 1 分単位に丸める
2. 集計単位(プロジェクトなど)ごとに、Claude Code・Codex・サブエージェント・並行セッション・束ねたリポジトリの分を 1 本の時間軸に合成する(同じ分は 1 回だけ数える)
3. イベントがあった分を稼働とし、次のイベントまでの空白が `gap_minutes`(既定 15 分)以下なら、その間も稼働とする
4. 別のプロジェクトどうしは重なってもそれぞれに数える。そのため「合計」は 24 時間を超えることがある。「実時間」は全体を 1 本の時間軸に合成した値
5. `claude -p`・`codex exec` などの自動実行は数えない(設定の `include_automated = true` で数える)。同じ分に対話のセッションがあれば、その分は数える
6. 議事録の frontmatter に開始・終了時刻がある会議は、その時間をリポジトリの属するプロジェクトの稼働に足す(次の「議事録の会議」)

測れるのは AI とやりとりしていた時間で、実際の作業時間の下限にあたります。議事録の無い会議など、ログに残らない時間は補正ファイルで足せます。

### 議事録の会議

リポジトリの `docs/minutes/` にある議事録の frontmatter に `date`・`start`・`end` があると、その会議の時間をプロジェクトの稼働に足します。会議中に AI を使っていた分は二重に数えません。

```yaml
---
title: 定例
date: "2026-09-28"
start: "14:00"
end: "15:00"
---
```

- `start`・`end` の無い議事録は数えず、レポートの末尾に件数を出します
- `_drafts/` のように `_` で始まるフォルダ・ファイルは読みません
- 置き場所は設定の `minutes` で変えられます(`[]` で読まない)

## 設定

`~/.config/worklog/config.toml`(無くても動きます)

```toml
timezone = "Asia/Tokyo"   # 省略時はシステムのローカル
gap_minutes = 15
include_automated = false # claude -p・codex exec などの自動実行も数えるなら true
roots = ["~/Developer"]   # git リポジトリでないときは、この直下のフォルダをプロジェクトとみなす
minutes = ["docs/minutes/**/*.md"]  # 議事録の置き場所(リポジトリからの相対 glob)。[] で読まない

# 旧パス → 現在のパス(前方一致。リポジトリを移動したときに)
[aliases]
"~/Documents/Develop/*" = "~/Developer/*"

# リポジトリ → プロジェクト(glob。上から順に最初に当たったもの。当たらなければリポジトリ名のまま)
[projects]
"分析基盤" = ["~/Developer/client-a/*"]
"ブログ" = ["~/Developer/blog", "~/Developer/blog-images"]

# リポジトリ → 案件(glob。上から順に最初に当たったもの)
[clients]
"Client A" = ["~/Developer/client-a/*"]
"個人" = ["~/Developer/*"]
```

作業ディレクトリから親をたどって見つけた git リポジトリを「リポジトリ」とし(git worktree は本体のリポジトリにまとめます)、`[projects]` でプロジェクトに、`[clients]` で案件に束ねます。案件はプロジェクト単位で決まります。どれにも当たらない時間は「(未分類)」として表示します。`worklog projects` で判定結果を確かめながら、`aliases` と `roots` を足してください。

補正は `~/.config/worklog/adjustments.csv` に書きます。`project` にはプロジェクト名もリポジトリ名も書けます。`minutes` は負の値も使えます。Excel で保存した CSV(UTF-8)も読めます。

```csv
date,project,minutes,note
2026-09-28,dashboard,60,定例
```

## Claude Code の skill

`skill/worklog/SKILL.md` を `~/.claude/skills/worklog/` に置くと、Claude Code に「今週の稼働と作業内容をまとめて」と頼めるようになります。skill は `worklog` の出力をそのまま見せ、`worklog material` の素材からプロジェクトごとの作業内容を要約します。

```bash
mkdir -p ~/.claude/skills/worklog
curl -fsSL https://raw.githubusercontent.com/Kyo1M/claude-worklog/main/skill/worklog/SKILL.md -o ~/.claude/skills/worklog/SKILL.md
```

## 対象外

- Codex の旧形式のログ(2025 年 8 月ごろまで。各行に時刻と作業ディレクトリが無い)

## 開発

```bash
uv run pytest
```

## ライセンス

MIT
