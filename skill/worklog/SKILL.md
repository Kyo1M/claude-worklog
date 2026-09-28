---
name: worklog
description: Claude Code と Codex のログから、プロジェクト・案件ごとの稼働時間をターミナルのバーで見せ、作業内容を要約する。「今日の稼働を見せて」「今週の稼働」「9 月の稼働と作業内容をまとめて」「案件別の稼働報告の下書き」「稼働時間を CSV で」「/worklog」などのリクエスト時に使う。数字は worklog CLI が出し、要約は CLI の素材をもとに書く。
---

# worklog

稼働時間の数字は `worklog` CLI が出す。この skill は、期間に合うコマンドを選んで結果を見せ、素材を読んで作業内容を要約する。

CLI が無いとき(`command -v worklog` が空)は、`uv tool install --editable <claude-worklog のリポジトリ>` での導入を案内して止まる。

## 1. 期間とまとめ方を決める

| 依頼 | 期間 | コマンド |
|---|---|---|
| 今日・昨日・特定の日 | 1 日 | `worklog day [YYYY-MM-DD\|yesterday]` |
| 今週・先週 | 月曜始まりの週 | `worklog week [週に含まれる日]` |
| 今月・特定の月 | 1 か月 | `worklog month [YYYY-MM]` |

- 「案件別」「クライアント別」「稼働報告」と言われたら `--by client` を付ける
- 補正前の数字を求められたら `--raw` を付ける
- 期間があいまいなら今日(日)・今週(週)・今月(月)を初期値にして進め、どの期間で出したかを書き添える

## 2. バーを見せる

コマンドを `--no-color` で実行し、出力をそのままコードブロックで見せる(色のエスケープはチャットで崩れるため)。数字を書き換えたり丸めたりしない。

見出しの「合計」は並行したプロジェクトをそれぞれに数えた値で、24 時間を超えることがある。「実時間」は全体を 1 本の時間軸に合成した値。聞かれたらこの違いを 1 文で説明する。

## 3. 作業内容を要約する(要約を求められたときだけ)

素材を Markdown で取る(JSON より短い)。

```bash
worklog material --date YYYY-MM-DD                                   # 1 日
worklog material --from YYYY-MM-DD --to YYYY-MM-DD --max-prompts 4   # 週
worklog material --from YYYY-MM-DD --to YYYY-MM-DD --max-prompts 2 --prompt-chars 80   # 月
```

素材はプロジェクトごとに、稼働時間・セッション(時刻・タイトル・依頼文)・期間内の自分のコミットを持つ。これを読んで、プロジェクトごとに次の形で書く。

```markdown
### <プロジェクト名>(<案件>) <稼働時間>
- <何をしたか。成果物・対象を名詞で特定する>
- ...(3〜5 行)
```

- 依頼文とコミットの両方に出てくる対象を優先し、会話の途中の相づち(「OK です」など)は拾わない
- 素材に無いことは書かない。推測で補うときは「〜とみられる」と書く
- 稼働が 15 分未満のプロジェクトはまとめて 1 行にする(「ほか: A 5m、B 3m」)
- 「(未分類)」はプロジェクトにできなかった時間。多いときは `worklog projects` で cwd を確かめ、`~/.config/worklog/config.toml` の `[aliases]`・`roots` での名寄せを提案する(設定は勝手に書き換えない)

## 4. 稼働報告の下書き(案件別を求められたとき)

`worklog month YYYY-MM --by client --no-color` の数字と、手順 3 の要約を案件ごとにまとめる。数字は AI とやりとりしていた時間の推定で、会議などを含まない下限であることを下書きの末尾に 1 行添える。補正が要る時間(会議など)は `~/.config/worklog/adjustments.csv` に `date,project,minutes,note` で書けば反映されることを案内する。

## 5. CSV が欲しいとき

```bash
worklog export --from YYYY-MM-DD --to YYYY-MM-DD --grain day|week|month [--by client] > worklog.csv
```

列は `period,client,project,minutes,hours`。保存先を聞かれなければカレントディレクトリに書き、パスを伝える。
