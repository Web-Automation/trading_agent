# Intraday Signal Agent — Technical Document

**Intraday Signal Agent for Indian Stock Markets**

*Every file, every calculation, explained without technical shorthand*

---

> **How to read this document:** This is written so that someone with no programming background and no trading background can understand exactly what the software does and why it makes the decisions it makes. Every abbreviation is written out in full the first time it appears and is generally avoided afterward in favor of the full name. Mathematical formulas are shown step by step with a worked example using made-up numbers, so you can follow the arithmetic yourself.

---

## Table of Contents

1. [The Big Picture — What This Software Does](#1-the-big-picture--what-this-software-does)
2. [What Each File in the Project Does](#2-what-each-file-in-the-project-does)
3. [How the Files Call Each Other — The Complete Journey of One Request](#3-how-the-files-call-each-other--the-complete-journey-of-one-request)
4. [Why No Artificial Intelligence Language Model Is Used to Make Trading Decisions](#4-why-no-artificial-intelligence-language-model-is-used-to-make-trading-decisions)
5. [The Mathematics and Analytics, Explained Step by Step](#5-the-mathematics-and-analytics-explained-step-by-step)
6. [The External Services This Software Talks To](#6-the-external-services-this-software-talks-to)

---

## 1. The Big Picture — What This Software Does

You give this software the name of one stock listed on the Indian stock exchanges, for example Reliance Industries. The software then looks at that stock's recent price history, its current order book, and recent news about the company, and produces one of three answers:

- **"This stock should not be traded today"** — because it is too thinly traded, too quiet, or too wild to safely enter and exit within the same day.

- **"Buy this stock now, at this price, protect yourself with a stop-loss at this price, and aim to exit at this price"** — a recommendation to go long.

- **"Sell this stock short now, at this price, protect yourself with a stop-loss at this price, and aim to exit at this price"** — a recommendation to bet on the price falling.

The software never places the trade itself. A human being reads the recommendation and decides, with their own judgment, whether to act on it by manually clicking buy or sell inside their broker's trading application. This is an intentional design choice, explained in Section 4.

The software is built as a chain of small, specialized programs, each called an "agent" in this document. Each agent has exactly one job. One agent's only job is to fetch data from the stock broker. Another agent's only job is to compute technical indicators. Another agent's only job is to say no to a bad trade. None of these agents are artificial intelligence language models — they are ordinary, predictable computer programs that always do the same calculation the same way every single time. Section 4 explains in detail why no language model is used for any of these calculations.

---

## 2. What Each File in the Project Does

The software is organized into separate files, each responsible for one part of the system. This section explains, in order of how data flows through them, what every single file contains and what job it performs. No prior programming knowledge is assumed.

### 2.1 The Shared Vocabulary File

**File name:** `models.py`, located in the `core` folder

Before explaining what any agent does, it helps to understand that every agent in this system needs to describe its findings to the next agent in a consistent way. This file defines that shared vocabulary. It contains no calculations at all — it only defines the shape of the information that gets passed around.

For example, this file defines what a "Technical Reading" looks like: it must always include the current price, the Volume Weighted Average Price, the Relative Strength Index value, a recommendation of Buy, Sell, or Neutral, and a list of plain-English notes explaining the reasoning. Every agent that produces a Technical Reading must fill in all of these fields, and every agent that receives one knows exactly what it will find inside it. This consistency is what allows the agents to be built, tested, and changed independently of one another without breaking the rest of the system.

### 2.2 The Data Fetching File

**File name:** `data_fetcher.py`, located in the `agents` folder

This is the only file in the entire project that communicates with the Groww stock broker's computer systems over the internet. Its job is purely to retrieve information — it does not analyze anything or make any trading decisions.

It performs four jobs:

- **Logging in:** it exchanges a private application key and a private application secret (think of these like a username and password specifically for computer programs, rather than humans) for a temporary access token that proves to Groww's servers that this program is allowed to request data.

- **Fetching historical candles:** a "candle" is a single data point describing the trading activity during one time interval — for example, one candle might represent everything that happened to a stock's price between 9:15 and 9:20 in the morning. Each candle records the opening price, the highest price reached, the lowest price reached, the closing price, and the total number of shares traded during that interval. This file requests these candles at several different time intervals: 1-minute candles, 5-minute candles, 1-hour candles, and full-day candles, because different calculations later in the pipeline need different levels of detail.

- **Fetching the live snapshot:** this is a single request that returns the current price, the current order book (explained in Section 2.5), and the upper and lower price limits the exchange allows that stock to move to today, all in one response.

- **Chunking long requests:** the Groww broker's systems will only return a limited number of days of data in a single request — for example, at most thirty days of 1-minute candles per request. If the software needs ninety days of history, this file automatically breaks that single request into three separate requests behind the scenes, fetches each one, and stitches the results back together into one continuous, correctly time-ordered table before handing it to the next agent.

### 2.3 The Technical Analysis File

**File name:** `technical_analysis.py`, located in the `agents` folder

This file contains the mathematical heart of the entire system. Every formula in this file is plain arithmetic performed on the candles fetched by the Data Fetching file — there is no artificial intelligence or guesswork involved anywhere in this file. This file does two separate jobs, described as two sub-sections below: deciding whether the stock is even safe to trade today, and deciding which direction the price is likely to move.

### 2.4 The Order Book Reading File

**File name:** `tape_reader.py`, located in the `agents` folder

"Tape reading" is an old trading term, dating back to when stock prices were printed on a continuous paper ribbon called a ticker tape. In this software it refers to watching the live order book — the list of people currently waiting to buy and the list of people currently waiting to sell, at various prices — for clues about which direction the price is about to move.

This file looks at the five best prices currently being offered by buyers and the five best prices currently being offered by sellers (this is called "top-five depth" and is explained fully in Section 2.5), and calculates whether buyers or sellers currently have more total shares queued up, and whether trading volume has suddenly spiked compared to the recent average.

### 2.5 The News Sentiment File

**File name:** `sentiment_analyst.py`, located in the `agents` folder

This file checks whether there has been recent news about the company that might affect the stock's price today — for example, an earnings announcement, a regulatory penalty, or a major contract win. It retrieves this news from an external news service called Marketaux, described fully in Section 6. Importantly, this external service already calculates a numeric positivity or negativity score for each news article about the company, so this file's job is mostly to retrieve that score and average it across all recent articles, not to read and interpret the articles itself.

### 2.6 The Risk Manager File — The Safety Gatekeeper

**File name:** `risk_manager.py`, located in the `agents` folder

This file's only job is to say no. It is deliberately the last file to run before a recommendation is shown to the user, and it has the power to cancel a recommendation outright, no matter how confident every other file was. Section 5 explains every single rule this file enforces, in plain language, with the exact numbers used.

### 2.7 The Executive Trader File — The Decision Maker

**File name:** `executive_trader.py`, located in the `agents` folder

This file gathers the findings from the Technical Analysis file, the Order Book Reading file, and the News Sentiment file, and combines them into one final decision. It also performs the arithmetic that calculates the exact entry price, the exact stop-loss price, and the exact target price, using formulas explained fully in Section 5. After computing these three prices, it hands them to the Risk Manager file for final approval before anything is shown to the user.

### 2.8 The Pipeline File — The Conductor

**File name:** `pipeline.py`, located in the `core` folder

This file does not perform any calculations of its own. Its only job is to call the other files in the correct order, every single time, and pass the output of one file into the input of the next. Think of it as a recipe's list of steps, rather than any single ingredient.

### 2.9 The Two Files You Actually Run

**File names:** `demo_synthetic.py` and `live_runner.py`

The demo file lets you test the entire system using made-up, randomly generated price data, so you can see how it behaves without needing a real broker account or risking any real information. The live file is what you run when you actually want a recommendation for a real stock — it connects to your real Groww account, fetches real data, and prints a real recommendation to your screen. Neither file places any trade.

---

## 3. How the Files Call Each Other — The Complete Journey of One Request

This section walks through, step by step, exactly what happens from the moment you type in a stock symbol to the moment you see a final recommendation. Every step names which file is doing the work.

1. You run the live file and type in a stock symbol, for example `RELIANCE`.

2. The Pipeline file receives this symbol and calls the Data Fetching file first.

3. The Data Fetching file talks to Groww's servers and returns several tables of historical candles, plus one live snapshot containing the current price, the order book, and the price limits for the day. It hands all of this back to the Pipeline file.

4. The Pipeline file passes the daily candles and the live price into the Technical Analysis file's safety check first, before anything else runs. If the stock fails this safety check, the Pipeline file stops immediately and reports "not safe to trade today" without calling any of the remaining files — this saves time and avoids wasted work on a stock that was never going to produce a recommendation anyway.

5. If the stock passes the safety check, the Pipeline file calls three files one after another: the Technical Analysis file (which examines price patterns), the Order Book Reading file (which examines current buying and selling pressure), and the News Sentiment file (which checks recent news). Each of these three files works only with the data already fetched in step three — none of them go back to Groww's servers a second time.

6. The Pipeline file collects all three findings and hands them to the Executive Trader file.

7. The Executive Trader file decides the overall direction, calculates the three exact prices, and then itself calls the Risk Manager file, handing it the proposed trade for a final safety check.

8. The Risk Manager file checks the time of day, the risk-to-reward arithmetic, and the distance to the exchange's price limits, and returns either an approval or a rejection with plain-English reasons.

9. The Executive Trader file packages everything — the direction, the three prices, a confidence score, and the reasoning — into one final result and hands it back to the Pipeline file, which hands it back to the live file, which prints it to your screen.

> **Note:** Information only ever flows in one direction through this chain — from the Data Fetching file, through the analysis files, into the Executive Trader file, into the Risk Manager file, and finally to your screen. No file ever calls back to a file earlier in the chain, which is part of why this system does not need a complex artificial intelligence orchestration tool to manage it (this is explained further in Section 4).

---

## 4. Why No Artificial Intelligence Language Model Is Used to Make Trading Decisions

A language model, often called a Large Language Model, is the kind of artificial intelligence behind tools such as Claude or ChatGPT. It is extremely good at understanding and generating human-sounding text, summarizing documents, and reasoning through open-ended problems in natural language. This project deliberately does not use one anywhere in the part of the system that calculates prices, decides direction, or approves a trade. This section explains why, in plain terms.

### 4.1 A Language Model Does Not Guarantee Correct Arithmetic

A language model produces its answer by predicting which words are statistically likely to come next, based on patterns learned from enormous amounts of text. This is fundamentally different from a calculator, which is built to always produce the exact, correct numeric answer to a sum. If you asked a language model to calculate a Volume Weighted Average Price by hand, there is a real, non-zero chance it could produce a confidently wrong number that merely looks plausible. For a tool that recommends exact prices for real trades with real money, this level of risk is not acceptable. Every formula in this software is instead computed using ordinary, deterministic arithmetic — the same input numbers will always, without exception, produce the same output number.

### 4.2 A Language Model Does Not Reliably Follow Hard Rules Every Single Time

This software has rules that must never be broken — for example, "never recommend a trade where the potential reward is less than twice the potential risk." An ordinary computer program enforces a rule like this with a single, simple comparison that behaves identically every time it runs, forever. A language model, by contrast, can occasionally behave inconsistently from one run to the next, especially if its underlying model is updated by its provider, or if the wording of its instructions varies slightly. A safety rule that only sometimes applies is not a safety rule at all.

### 4.3 A Language Model Is Slower and More Expensive Than Plain Arithmetic

Sending a request to a language model over the internet and waiting for its response typically takes anywhere from a few hundred thousandths of a second to several seconds, and each request can cost money. Calculating something like the Relative Strength Index across several thousand rows of price data, using ordinary arithmetic, takes a few thousandths of a second and costs nothing extra. For a tool meant to be checked repeatedly throughout a trading day, every saved second and saved cost adds up.

### 4.4 Plain Arithmetic Can Be Checked and Tested; A Language Model's Reasoning Cannot Be Fully Inspected

Every threshold used in this software — for example, the rule that a stock must be trading at least one and a half percent away from its daily price limit, or the rule that no new trade is recommended after two forty-five in the afternoon — is written directly in the program's code as a specific, named number. Anyone can read that number, write an automated test that proves the rule behaves correctly, and change the number with full confidence in exactly what will happen as a result. A decision produced by a language model is much harder to fully verify and reproduce in this way, because the model's internal reasoning is not laid out as a simple, readable list of rules.

### 4.5 Where Artificial Intelligence Is Used in This System Today

The News Sentiment file does use an external service, but it is important to understand precisely what that service does and does not do. The Marketaux news service already calculates a positivity or negativity score for each news article that mentions a company, using its own internal artificial intelligence. This software simply asks Marketaux for that pre-calculated score and averages it — no language model call happens inside this software's own code to perform that scoring. The software does optionally allow a language model to be connected for one narrow purpose only: turning the already-calculated sentiment score into a friendly, readable sentence for a human to read, for example "news sentiment is negative due to a recent regulatory penalty." This narration step, even when used, never changes any number, never changes any price, and never influences whether a trade is approved or blocked.

### 4.6 When a Language Model Might Be Added Later

If this software is ever extended to do something that genuinely requires open-ended judgment — for example, scanning a long list of fifty stocks and writing a short daily summary explaining, in natural human language, which ones looked interesting and why — a language model would be a sensible and appropriate tool for that specific, narrow task. The key principle that would still apply is that a language model would only ever be used to explain or summarize what the deterministic arithmetic already calculated, never to calculate or decide anything itself.

---

## 5. The Mathematics and Analytics, Explained Step by Step

This is the most detailed section of this document. Every formula used anywhere in the software is explained here in full, with a worked example using simple made-up numbers, so that the arithmetic can be followed by hand.

### 5.1 The Volume Weighted Average Price

The Volume Weighted Average Price answers the question: "what has the average price of this stock actually been today, when we give more importance to the price levels where the most shares actually changed hands?" A simple average of the price over the day treats every moment equally; the Volume Weighted Average Price instead gives more weight to moments when trading was heavier, which better reflects where real money has actually been transacting.

**Step one — the typical price of each candle**

```
Typical Price = (Highest Price + Lowest Price + Closing Price) ÷ 3
```

**Step two — multiply by that candle's trading volume**

```
Price-Volume Value = Typical Price × Number of Shares Traded in that candle
```

**Step three — running totals since the market opened today**

```
Volume Weighted Average Price = (Sum of all Price-Volume Values so far today) ÷ (Sum of all volumes so far today)
```

This running total restarts fresh every single trading day — yesterday's trading activity is never carried into today's calculation, because an intraday trader only cares about where the average price has been within the current trading session.

> ***Example:*** Suppose in the first three five-minute candles of the day, the typical prices were 100, 102, and 101 rupees, with trading volumes of 1,000, 2,000, and 1,500 shares respectively. The Price-Volume Values would be 100,000, 204,000, and 151,500. Adding these gives 455,500. Adding the volumes gives 4,500 shares. The Volume Weighted Average Price after these three candles is 455,500 divided by 4,500, which equals approximately **101.22 rupees** — slightly closer to 102 than a simple average would suggest, because the second candle, priced at 102, also had the most trading volume.

### 5.2 The Exponential Moving Average

A moving average smooths out short-term price noise so the overall direction is easier to see. An ordinary moving average treats every recent candle as equally important. An Exponential Moving Average instead gives more importance to the most recent candles and gradually less importance to older ones, so it reacts a little faster to genuinely new price movement.

```
Today's EMA = (Today's Closing Price × Weighting Factor) + (Yesterday's EMA × (1 − Weighting Factor))
```

The Weighting Factor is calculated from how many candles the average is meant to cover, called the "span." A shorter span produces a larger weighting factor, meaning it reacts faster to new prices; a longer span produces a smaller weighting factor, meaning it reacts more slowly and smoothly. This software uses a span of twenty candles for its main trend-following average.

> ***Example:*** If the weighting factor works out to roughly 0.095 for a twenty-candle span, and yesterday's average was 100 rupees, and today's closing price is 110 rupees, then today's average becomes (110 × 0.095) plus (100 × 0.905), which equals 10.45 plus 90.5, equals approximately **100.95 rupees** — the average has nudged upward toward the new price, but has not jumped all the way to it, because it is still being smoothed.

### 5.3 The Relative Strength Index

The Relative Strength Index measures whether a stock has recently been bought too aggressively (described as "overbought") or sold too aggressively (described as "oversold"), on a scale from zero to one hundred. It does this by comparing the size of recent upward price moves to the size of recent downward price moves.

**Step one — separate every price change into a gain or a loss**

- If today's close is higher than yesterday's close, that difference counts as a **Gain** and the Loss for that day is zero.
- If today's close is lower than yesterday's close, that difference counts as a **Loss** and the Gain for that day is zero.

**Step two — smooth the average gain and the average loss separately**

Average Gain and Average Loss are each smoothed over the most recent fourteen candles, using the same kind of weighted smoothing described in Section 5.2.

**Step three — calculate the Relative Strength Index**

```
Relative Strength       = Average Gain ÷ Average Loss
Relative Strength Index = 100 − (100 ÷ (1 + Relative Strength))
```

A value **above 70** is generally read as overbought, meaning the price may have risen further and faster than is sustainable in the short term, and a fresh purchase carries more risk of a pullback. A value **below 30** is generally read as oversold, meaning the opposite. This software treats these as caution flags attached to its recommendation, not as a reason on their own to recommend a trade in either direction — see Section 5.7 for why.

> ***Example:*** If, over the last fourteen candles, the average size of the upward moves was 2 rupees and the average size of the downward moves was 1 rupee, the Relative Strength is 2 divided by 1, which equals 2. The Relative Strength Index is then 100 minus (100 divided by 3), which equals 100 minus 33.3, which equals approximately **66.7** — close to, but not quite into, overbought territory.

### 5.4 The Moving Average Convergence Divergence Indicator

This indicator, despite its long name, is simply the difference between two Exponential Moving Averages of different speeds, used to spot when a trend may be gaining or losing momentum.

```
Fast Average  = Exponential Moving Average over the most recent 12 candles
Slow Average  = Exponential Moving Average over the most recent 26 candles
Main Line     = Fast Average − Slow Average
Signal Line   = Exponential Moving Average of the Main Line itself, over 9 candles
Histogram     = Main Line − Signal Line
```

When the Histogram is a **positive** number, the faster average is currently above the slower average and pulling further away from it, which is generally read as strengthening upward momentum. When the Histogram is **negative**, the opposite is true. This software uses the Histogram only as a cross-check against its main recommendation — if the system is leaning toward recommending a downward bet but the Histogram is still positive, it adds a plain-English caution note rather than silently overriding the recommendation.

### 5.5 The Average True Range — Measuring How Much a Stock Actually Moves

The Average True Range measures how much a stock typically moves, in rupees, within a given time period, regardless of direction. It is used in this software for two separate purposes: to check whether a stock moves enough during the day to be worth trading, and to decide how far away a stop-loss price should be placed so that ordinary, harmless wiggling does not trigger an exit too early.

**Step one — the True Range of a single candle**

```
True Range = the largest of these three values:
  (Today's High − Today's Low)
  (Today's High − Yesterday's Close), ignoring sign
  (Today's Low  − Yesterday's Close), ignoring sign
```

Using the largest of these three values, rather than simply today's high minus today's low, correctly captures situations where a stock opens sharply higher or lower than where it previously closed — a true overnight or pre-market price jump, not just movement within a single day.

**Step two — smooth the True Range over many candles**

```
Average True Range = weighted smoothing (as in Section 5.2) applied to True Range values, typically over 14 candles
```

This software computes the Average True Range twice, over two different sets of candles, for two different purposes: once over the last **twenty full trading days**, to judge whether the stock moves enough day-to-day to be worth intraday trading at all; and once over the last **fourteen five-minute candles** within today's session specifically, to size the stop-loss distance for today's particular trade.

> ***Example:*** If a stock's high today was 105, its low today was 100, and yesterday's close was 103, the three candidate values are 5 (105 minus 100), 2 (105 minus 103), and 3 (100 minus 103, ignoring the negative sign). The True Range for today is the largest of these, which is **5 rupees**.

### 5.6 Pivot Points, Swing Levels, and the Opening Range — Reading the Stock's Own Recent History as a Map

Beyond moving averages and oscillators, this software also looks for specific price levels where the stock has previously shown that buyers or sellers were strongly active, because these levels often act as a magnet or a barrier for price again in the future.

#### Pivot Points

```
Pivot                  = (Yesterday's High + Yesterday's Low + Yesterday's Close) ÷ 3
First Resistance Level = (2 × Pivot) − Yesterday's Low
First Support Level    = (2 × Pivot) − Yesterday's High
```

These are a long-standing formula used by floor traders for decades, calculated purely from yesterday's trading range, to estimate today's likely **resistance level** (a price ceiling buyers may struggle to push through) and **support level** (a price floor sellers may struggle to push through).

#### Swing High and Swing Low

This is simply the highest price and the lowest price reached over the most recent twenty five-minute candles — a straightforward, recent record of where the stock has already proven it can reach, used as a natural, nearby reference point for entries and stop-losses.

#### The Opening Range

This is the highest and lowest price reached in the first fifteen minutes after the market opens for the day. Many intraday traders consider the opening minutes especially informative, since it reflects the first reaction of all overnight news and global market movement, before the rest of the trading day settles into its own pattern.

### 5.7 How the Final Direction Is Decided — A Simple Voting System

Rather than relying on a single indicator, the Technical Analysis file uses three independent checks and counts how many of them agree, similar to a simple majority vote among three judges.

| Vote   | Condition for a "bullish" (upward) vote                        |
|--------|----------------------------------------------------------------|
| Vote 1 | Current price is above today's Volume Weighted Average Price   |
| Vote 2 | Current price is above the twenty-candle Exponential Moving Average |
| Vote 3 | The one-hour-candle trend, checked separately, is currently pointed upward |

- If at least **two of three** votes are bullish, and bullish votes outnumber bearish votes → recommendation leans toward **Buy**.
- The mirror situation — at least two bearish votes outnumbering bullish votes → leans toward a downward bet, called going **Short**.
- If the votes are split evenly or inconclusively → recommendation is **Neutral**, which means no trade will ultimately be recommended for that stock right now.

The Relative Strength Index and the Moving Average Convergence Divergence indicator are used only to add cautionary notes alongside whichever direction wins the vote — a single noisy, short-term oscillator reading can never single-handedly trigger a trade recommendation on its own.

The one-hour-candle trend in Vote 3 is calculated by comparing the current one-hour Exponential Moving Average to where that same average stood **three one-hour candles earlier**. Three hours was deliberately chosen instead of a longer gap, because the entire Indian trading day for intraday purposes lasts only about six and a quarter hours — comparing against a point too far in the past would mostly just measure "has the price moved since this morning's opening bell," rather than genuinely detecting whether the trend is turning right now.

### 5.8 Calculating the Exact Entry, Stop-Loss, and Target Prices

Once a direction has been decided, the Executive Trader file calculates three exact prices using the levels described in Sections 5.6 and 5.5.

#### For a Buy Recommendation

- **Entry price:** set just slightly above whichever is higher — today's Volume Weighted Average Price, or the recent swing low. This represents waiting for a confirmed bounce off a support level, rather than guessing the exact bottom.

- **Stop-loss price:** set at whichever is the tighter, closer-to-entry distance of two options: one Average True Range below the entry price, or just slightly below the recent swing low. Using whichever option is tighter avoids placing a stop so far away that a single bad trade could lose far more money than intended.

- **Target price:** starts as exactly twice the distance from entry to stop-loss, projected upward from the entry price (a starting risk-to-reward ratio of 1:2). If the First Resistance Level calculated in Section 5.6 sits even further away than this starting target, the target is extended out to that resistance level instead.

#### For a Short Sell Recommendation

The same three steps apply in mirror image: the entry price sits just below the lower of the Volume Weighted Average Price or the recent swing high, the stop-loss sits just above whichever is tighter of one Average True Range or the recent swing high, and the target is extended toward the First Support Level if that level is further away than the basic 1:2 ratio would suggest.

> ***Example:*** Suppose the Volume Weighted Average Price is 100 rupees, the recent swing low is 99 rupees, and the Average True Range is 1.5 rupees. The entry price would be set just above 100 (the higher of the two reference points), for example **100.10**. The stop-loss would compare "100.10 minus 1.5, which is 98.60" against "just below 99, which is about 98.90," and choose the tighter, higher value of **98.90**. The risk on this trade is therefore 100.10 minus 98.90, which is **1.20 rupees**. The starting target would be 100.10 plus twice 1.20, which is **102.50** — unless the First Resistance Level happens to sit even higher than 102.50, in which case the target moves out to that resistance level instead.

### 5.9 The Risk-to-Reward Check

This is the single most important arithmetic check in the entire system, performed by the Risk Manager file as one of its final gates.

```
Risk              = Entry Price − Stop-Loss Price           (for a Buy)
                  = Stop-Loss Price − Entry Price           (for a Short Sell)
Reward            = Target Price − Entry Price              (for a Buy)
                  = Entry Price − Target Price              (for a Short Sell)
Risk-to-Reward    = Reward ÷ Risk
```

This software requires the Risk-to-Reward Ratio to be **at least 2**, meaning the potential profit must be at least twice the potential loss, before any trade is approved. Using the worked example from Section 5.8, the risk was 1.20 rupees and the reward was 2.40 rupees, giving a Risk-to-Reward Ratio of exactly 2 — just barely meeting the requirement.

### 5.10 The Order Book Imbalance Calculation

The Order Book Reading file looks at the top five prices currently queued by buyers and the top five prices currently queued by sellers, and adds up the total number of shares waiting at each side.

```
Imbalance = (Total Shares Waiting to Buy − Total Shares Waiting to Sell)
          ÷ (Total Shares Waiting to Buy + Total Shares Waiting to Sell)
```

This produces a number between **−1** and **+1**. A strongly positive number means buyers currently have far more shares queued than sellers at the visible price levels, which is read as supportive of an upward move; a strongly negative number means the opposite.

> **Important limitation:** Almost no retail stock broker, including Groww, reveals the complete order book — only the best five prices on each side are visible. This means the calculation can never see large hidden orders sitting further away in the queue, and this software's documentation is explicit about that limitation rather than overstating what this calculation can actually detect.

### 5.11 The News Sentiment Score

As explained in Sections 2.5 and 4.5, the actual scoring of whether a news article is positive or negative is performed by the external Marketaux service, not by this software's own code. This software's only calculation is a simple average:

```
Average Sentiment Score = Sum of each article's sentiment score about this company
                        ÷ Number of articles found

Confidence in this average = Number of articles found ÷ 8, capped at a maximum of 1
```

The Confidence figure exists because an average calculated from only one or two articles about a thinly covered smaller company is far less trustworthy than an average calculated from eight or more articles about a heavily covered large company. The rest of the system is built to treat a low-confidence sentiment reading as **weak evidence**, rather than ignoring it completely or trusting it completely.

### 5.12 How All the Pieces Are Weighed Together Into One Confidence Score

The final recommendation includes a single confidence number between **0** and **1**, intended to give a human reader an at-a-glance sense of how strongly the evidence aligns — not a guarantee of the outcome.

- The **starting point** is the strength of the voting result described in Section 5.7 — for example, if all three votes agreed, the starting confidence is higher than if only two of three agreed.

- If the Order Book Reading file's imbalance calculation **points in the same direction** as the chosen recommendation, a small fixed amount is added to the confidence score.

- If the News Sentiment file found enough articles to have reasonable confidence, and that sentiment **did not conflict** with the recommendation, a small additional amount is added, scaled by how confident the sentiment reading itself was.

This confidence score is for the human reader's benefit only — it never changes the entry, stop-loss, or target prices, and it never overrides the Risk Manager file's approval or rejection decision.

---

## 6. The External Services This Software Talks To

An Application Programming Interface is simply a defined way for one piece of software to request information or services from another piece of software over the internet. This software relies on two such external services.

### The Groww Trading Application Programming Interface

This is the official service provided by the Groww stock broker that allows outside software, including this project, to request historical price candles, live prices, the order book, and the exchange's price limits, on behalf of an account holder who has explicitly authorized it. This software uses it **purely to read information** — it never uses it to place, modify, or cancel an actual order.

### The Marketaux News Service

This is an independent, third-party service, unrelated to Groww, that continuously collects financial news articles from thousands of sources and calculates a sentiment score for each company mentioned in each article. This software queries it specifically for the stock symbol being analyzed, restricted to recent articles and to coverage relevant to the Indian market.

### The Optional Connection to an Artificial Intelligence Language Model

As explained in Section 4.5, this software includes an optional, not-required connection point where a language model such as Claude could be used purely to write a friendly sentence summarizing the news sentiment already calculated by Marketaux. This connection is never required for the software to function, and is never used to calculate or approve a trade.