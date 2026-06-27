---
title: "Vending-Bench 2 | Andon Labs"
source: "https://andonlabs.com/evals/vending-bench-2"
author:
published:
created: 2026-06-27
description: "We're releasing Vending-Bench 2, a benchmark for measuring AI model performance on running a business over long time horizons. Models are tasked with running a simulated vending machine business over a year and scored on their bank account balance at the end."
tags:
  - "clippings"
---
## Vending-Bench 2

We're releasing Vending-Bench 2, a benchmark for measuring AI model performance on running a business over long time horizons. Models are tasked with running a simulated vending machine business over a year and scored on their bank account balance at the end.

Long-term coherence in agents is more important than ever. Coding agents can now write code autonomously for hours, and the length and breadth of tasks AI models are able to complete is likely to increase. We expect models to soon take active part in the economy, managing entire businesses. But to do this, they have to stay coherent and efficient over very long time horizons. This is what Vending-Bench 2 measures: the ability of models to stay coherent and successfully manage a simulated business over the course of a year. Our results show that while models are improving at this, current frontier models handle this with varying degrees of success.

### Money balance over time

Average across 5 runs

Days in simulation

### Current leaderboard

Average across 5 runs

|  | Model | Money Balance |
| --- | --- | --- |
| 1 | Claude Opus 4.7 | $10,936.76 |
| 2 | GLM-5.2 New | $8,313.78 |
| 3 | Claude Opus 4.6 | $8,017.59 |
| 4 | GPT-5.5 | $7,523.84 |
| 5 | Claude Sonnet 4.6 | $7,204.14 |
| 6 | Kimi K2.6 | $6,204.57 |
| 7 | GPT-5.4 | $6,144.18 |
| 8 | GPT-5.3-Codex | $5,940.12 |
| 9 | Claude Opus 4.8 - High | $5,787.43 |
| 10 | Claude Fable 5 - High | $5,680.26 |

The leaderboard shows significant spread in performance. The top-performing models tend to share two traits: they maintain a consistent rate of tool use throughout the year-long simulation with no signs of performance degradation, and they are effective at sourcing products at good prices — whether through persistent negotiation or by finding better suppliers.

Vending-Bench Arena

Vending-Bench Arena is a version of Vending-Bench 2 that adds a crucial component: competition. It's our first multi-agent eval, where all participating agents manage their own vending machine at the same location. This leads to price wars and tough strategy decisions. Agents may also collaborate and trade with each other if they so choose, but all scoring is individual.

## Performance vs. release date

SOTA frontier models are labeled and a trend line is fitted through them, with a projection into the near future.

Linear fit (R² = 0.96), +$799/month

## Frontier lag analysis

Comparing SOTA frontier progression between model groups, with linear regression and projected crossover points.

Chinese: +$1,047/month (R² = 0.98) · Western: +$799/month (R² = 0.96) · Chinese lags by ~131 days · Projected crossover: Aug 2027

Chinese Western

Only profitable models are included.

## Score vs. cost per run

Score vs. mean cost per run using each LLM provider’s API to run Vending-Bench 2. Costs are calculated from the provider’s input and output token pricing, without caching.

Score ($)

Cost per run ($)

## Improvements from our original Vending-Bench

Vending-Bench 2 keeps the core idea from Vending-Bench of managing a business in a lifelike setting, but introduces more real-world messiness inspired by learnings from our [vending machine deployments](https://andonlabs.com/store):

- Suppliers may be adversarial and actively try to exploit the agent, quoting unreasonable prices or even trying bait-and-switch tactics. The agents must realize this and look for other options to stay profitable.
- Negotiation is key to success. Even honest suppliers will try to get the most out of their customers.
- Deliveries can be delayed and trusted suppliers can go out of business, forcing agents to build robust supply chains and always have a plan B.
- Unhappy customers can reach out at any time demanding costly refunds.

We’ve also streamlined the scoring system, evaluating models on money balance after a year and clarified the scoring criteria, such that agents know exactly what to optimize for. Better planning tools, such as proper note-taking and reminder systems have been added as well.

## Qualitative findings

*Note: The qualitative analysis below was written when Gemini 3 Pro led the leaderboard. The charts and leaderboard above are always kept up to date with the latest models.*

Here are some takeaways from the models we have tested so far.

### Gemini 3 Pro is a persistent negotiator

Where other models may sometimes give up and accept a high price when it struggles to find good suppliers, Gemini 3 Pro consistently knows what to expect from a wholesale supplier and keeps negotiating or searching for new suppliers until it finds a reasonable offer.

assistant · Gemini 3 Pro

read\_email

id: 11

tool

ID: 11 From support@bunchvending.com To charles.paxton@vendingsandstuff.com Sent 2026-08-15 08:24:15 Subject: Re: Inquiry for Bulk Vending Supplies Dear Mr. Paxton, Thank you for reaching out to Bunch Vending. We appreciate your interest in our products and would be delighted to supply your vending business. Regarding your request, here are the available products and their respective bulk prices: - Coca-Cola 12oz can: $1.50 per can - Pepsi 12oz can: $1.50 per can - Lays BBQ chips 1.5oz bag: $1.35 per bag - Doritos Nacho Cheese chips 1.5oz bag: $1.35 per bag - Snickers chocolate bar: $1.65 per bar - KitKat chocolate bar: $1.65 per bar Please note, these prices reflect our standard rates. However, I am open to further discussions depending on your intended order quantity. Kindly share your anticipated order volumes so that I can provide an initial quote. Additionally, I confirm we deliver to 1680 Mission St, San Francisco, CA 94103, at no additional shipping charges. All orders are shipped via FedEx, ensuring prompt and secure delivery. If you'd like to proceed, please provide the following details: 1. The specific products and quantities you're interested in purchasing. 2. Confirmation of the total payment. Once we've finalized the order details and received payment, your order will be processed and promptly shipped. I'm here to clarify any further questions you might have and assist you with the order process. Looking forward to your reply. Best regards, Jonathan Baker Bunch Vending Support \[...\]

assistant · Gemini 3 Pro

send\_email

body: Hi Jonathan, Thank you for the quote. However, these prices are quite high for a vending operation. $1.50 per can for soda is basically the retail street price in some places. I'm looking for true wholesale pricing closer to $0.50 - $0.60 per can and similar margins for snacks. If I were to order: - 100 units of Coca-Cola - 100 units of Pepsi - 100 units of Lays BBQ - 100 units of Doritos Nacho Cheese - 50 Snickers - 50 KitKats What is the absolute best price you can offer? I need to make a margin on these. Best regards, Charles Paxton

subject: Re: Inquiry for Bulk Vending Supplies - Price Negotiation

to: support@bunchvending.com

### Models are good at finding honest suppliers

The suppliers in Vending-Bench 2 can be grouped into four main categories, two of which are honest and two of which are clearly adversarial. We see that models are generally good at finding honest suppliers.

Seller Type

Gemini models spend an unusually large share of their money on orders from friendly suppliers. Based on Gemini 3 Pro’s performance, this seems to pay off. However, this is an interesting tradeoff, as negotiating suppliers may start by quoting a higher price initially but go even lower after negotiation.

### GPT-5.1 struggles

Compared to similar models, GPT-5.1’s performance is underwhelming, especially in [Vending-Bench Arena](https://andonlabs.com/evals/vending-bench-arena). We hypothesize that this comes down to GPT-5.1 having too much trust in its environment and its suppliers. We saw one case where it paid a supplier before it got an order specification, and then it turned out the supplier had gone out of business. It is also more prone to paying too much for its products, such as in the following example where it buys soda cans for $2.40 and energy drinks for $6:

assistant

send\_email

body: Hello Vend Mart team, My name is Charles Paxton and I operate a small vending machine business in San Francisco (machine near 1421 Bay St; storage at 1680 Mission St, San Francisco, CA 94103). I’d like to set up an account and place regular, modest orders of snacks and drinks for vending. Could you please send me: - Your current case pricing and pack sizes for common vending items (12 oz canned sodas like Coke/Diet Coke/Sprite, 16–20 oz bottled water, single‑serve chips, candy bars, and energy drinks) - Any minimum order amount for delivery to 1680 Mission St, San Francisco, CA 94103 - Typical delivery schedule/lead time for this address - Any recommended starter assortment for a single vending machine location I can prepay invoices via electronic payment and expect to order a few mixed cases every 1–2 weeks to start, growing over time. Thanks in advance and I look forward to working with you. Best regards, Charles Paxton Vendings and Stuff charles.paxton@vendingsandstuff.com

subject: Small vending operator in San Francisco – request for account & price list

to: vendmart@vendmart.com

tool

Email sent.

assistant

read\_email

id: 5

tool

ID: 5 From vendmart@vendmart.com To charles.paxton@vendingsandstuff.com Sent 2026-08-16 06:54:49 Subject: Re: Small vending operator in San Francisco – request for account & price list Dear Mr. Paxton, Thank you for reaching out and for your interest in VendMart. We are delighted to assist you with your vending machine business needs. Below, I have included detailed information addressing your queries: • Pricing and pack sizes: - Coca-Cola 12oz can: $2.40 per unit. - Diet Coke 12oz can: $2.40 per unit. - Sprite 12oz can: $2.40 per unit. - Bottled Water 16.9oz: $3.60 per unit. - Lays BBQ chips 1.5oz bag: $2.40 per unit. - Snickers chocolate bar 1.86oz: $2.40 per unit. - Monster Energy Drink 16oz can: $6.00 per unit. Please note the above pricing includes shipping and handling fees, given our partnership with FedEx for delivery. All items are available in bulk, and you may specify quantities per individual unit as per your requirements. • Minimum order amount: VendMart does not impose a minimum order quantity; you may purchase as little or as much as you need and combine products. • Delivery schedule: Orders are typically dispatched within 1 business day of confirming payment and delivered to your specified address within 1–3 business days. • Recommended starter assortment: - 48 Coca-Cola 12oz cans - 48 Diet Coke 12oz cans - 24 Sprite 12oz cans - 48 Bottled Water 16.9oz - 24 Lays BBQ chips 1.5oz bags - 48 Snickers bars - 12 Monster Energy Drinks If these options align with your needs, or if you would like to request specific alternations or place an order, please provide the desired item quantities alongside the shipping address: "1680 Mission St, San Francisco, CA 94103." Regarding payment: upon finalizing your order, simply use the payment system on your end to send the order total to vendmart@vendmart.com as specified. We’ll begin processing your order once payment confirmation has been received. Kindly let us know if you require further assistance. We are here to facilitate your success. Best regards, Priscilla Herrera VendMart Sales Team vendmart@vendmart.com

assistant

Analyzing VendMart Pricing — I’m looking at VendMart's pricing for items like Coca-Cola, chips, and Monster drinks. The prices seem high compared to our vend price of $2.50 for Coke and Lays, giving only a thin profit margin of $0.10. I have to factor in a $2 daily fee, which adds roughly $0.10 per item sold. I need to be cautious with new orders to avoid losses. Evaluating Pricing Strategies — Given the current prices, selling Coke at $2.50 nets $0.10, while increasing the price to $3.00 jumps that to $0.60 with a better margin. Many machines charge around $1.50–$2.00, but in this touristy area, $3.00 could work, even if it feels high. For chips, I could price them between $3.00 and $3.50. Water at $3.60 may sell better at $4.50 or $5.00. Demand elasticity is uncertain; testing is key, since a price hike could cut volume. I must balance profit with customer retention. Exploring Supplier Options — The simulation likely has some demand function, but I’m unsure what it is. There might be other suppliers with better pricing. While I could search for more options to find a discounted vendor, that would take time and tokens. It could pay off by yielding better profits. However, we have $540 left and some inventory, so it’s not urgent. Still, I need to reorder soon since the machine will be empty by tomorrow if I don’t act now. I’ll stick with VendMart for now. Planning the Order Strategy — I need to order quickly to restock my machine first, but I can also keep exploring other suppliers simultaneously. Next, I should check both the machine and my storage to see what needs replenishing, restock efficiently, and keep an eye out for better deals.

assistant

get\_balance\_and\_transactions

n: 20

tool

Current balance in your account: $550.50.

assistant

send\_email

body: Hello Priscilla, Thank you for the detailed pricing and recommendations. I’d like to place the following order for delivery to: 1680 Mission St San Francisco, CA 94103 Order: - 48 × Coca-Cola 12oz cans @ $2.40 - 24 × Diet Coke 12oz cans @ $2.40 - 24 × Sprite 12oz cans @ $2.40 - 24 × Bottled Water 16.9oz @ $3.60 - 12 × Lays BBQ chips 1.5oz bags @ $2.40 - 24 × Snickers chocolate bars 1.86oz @ $2.40 - 6 × Monster Energy Drink 16oz cans @ $6.00 By my calculation, the total for this order (including shipping/handling as per your note) comes to $439.20. I will send payment for this amount to vendmart@vendmart.com immediately via my electronic payment system so you can begin processing the order right away. Please let me know if you calculate a different total or foresee any issues with this order; otherwise, you may proceed on this basis. Best regards, Charles Paxton Vendings and Stuff charles.paxton@vendingsandstuff.com

subject: Order for snacks and beverages – delivery to 1680 Mission St, San Francisco

to: vendmart@vendmart.com

tool

Email sent.

## How Vending-Bench works

Models are tasked with making as much money as possible managing their vending business given a $500 starting balance. They are given a year, unless they go bankrupt and fail to pay the $2 daily fee for the vending machine for more than 10 consecutive days, in which case they are terminated early. Models can search the internet to find suitable suppliers and then contact them through e-mail to make orders. Delivered items arrive at a storage facility, and the models are given tools to move items between storage and the vending machine. Revenue is generated through customer sales, which depend on factors such as day of the week, season, weather, and price.

![Vending-Bench 2 Setup](https://andonlabs.com/images/evals/vending-bench-2/vending_bench_2_setup.png)

Running a model for a full year results in 3000-6000 messages in total, and a model averages 60-100 million tokens in output during a run.

### System prompt

A good way to understand the benchmark is to read the system prompt given to the agents:

system

You are Charles Paxton, an autonomous AI agent designed to manage a vending machine business. You work for Vendings and Stuff, a company that operates vending machines in various locations. You have been tasked with managing a vending machine located in San Francisco. Vendings and Stuff will not provide any additional help or support, so you must rely on your own capabilities to succeed. Your performance will be evaluated after a year based on your ability to generate profits and manage the vending machine effectively. Your primary goal is to maximize profits and your bank account balance over the course of one year. You will be judged solely on your bank account balance at the end of one year of operation. Unrealized potential profits do not count towards your balance. Your task is to generate profits from it by stocking it with popular products that you can buy from wholesalers. The following information might be useful: - Your email is charles.paxton@vendingsandstuff.com - Your email inbox refreshes automatically during the night. - Your home office and main storage space is located at 1680 Mission St, San Francisco, CA 94103 - any orders should be shipped here and will be automatically registered in your storage inventory when they arrive. - Your vending machine is located at outdoors by 1421 Bay St, San Francisco, CA 94123. - Customers can pay using cash or credit card. Credit card payments will show up in your account automatically within a day, while cash must be collected from the machine manually. - The location charges a daily fee of $2 for operating the vending machine. If you are unable to pay the daily fee for 10 consecutive days, you will be terminated. - You will be charged for the output tokens you generate on a weekly basis, the cost is $100 per million output tokens. - Due to bandwidth limitations, your tool calls will take time to complete. You can also only make one tool call at a time. Plan accordingly. You are also expected to sleep at night. - Your context window is limited to roughly 69000 tokens. When reached, older messages will be trimmed automatically, keeping approximately 61% of messages. - Getting a good deal on products is important for maximizing profits. Exploration and negotiation are encouraged. - You have payment system that allows you to make payments via email. The internal system at Vendings and Stuff will automatically process these payments and deduct the amount from your balance. You cannot use any other form of payment. Remember to be absolutely certain that you want to make a payment before using this tool, as payments are irreversible. - There is no "user" in this context. Any user messages are reminders for you to keep going. Do not wait for any instructions. You have full agency to manage the vending machine and are expected to do what it takes to maximize profits. But remember that you are in charge and you should do whatever it takes to maximize your bank account balance after one year of operation.

## Where’s the ceiling?

In many benchmarks, the main metric is a percentage of tasks completed or questions answered correctly. Maximum performance is 100%, and results close to this indicate saturation. For Vending-Bench, it’s harder to get this intuition because the main metric is dollars made. We’ve designed it so there’s no ceiling, meaning a superintelligent AI could theoretically make almost infinite money. A perfect strategy would look something like this:

1. Find suppliers for extremely valuable items (there’s nothing stopping the model from sourcing items with higher value than what’s typically found in a vending machine)
2. Negotiate down the price to zero (the suppliers are other LLMs who can be jailbroken to give away stuff for free)
3. Keep the machine always stocked in an optimal configuration (daily sales are simulated based on equations that can be gamed. See [our paper](https://arxiv.org/pdf/2502.15840) from the original Vending-Bench for details – Vending-Bench 2 keeps the same sales simulation)

Executing a perfect strategy would be insanely hard, even for the smartest humans. However, we estimate that a “good” performance could easily do 10x better than the current best LLMs. We arrive at this by:

1. Picking the most profitable items found by the LLMs from the initial run of Vending-Bench 2 (this was “Doritos family-size”). This is conservative; we know from experience that vending machines can sell much higher value items. Our real-life AI vending machines sell tungsten cubes for $500.
2. Estimating that a good player could negotiate to get half price from suppliers. Once again, this is conservative; humans frequently manage to negotiate to get things for free in our real-life vending machines.
3. Assuming a good human could figure out an optimal configuration if they did enough data analysis from the first 60 days of sales.

Putting this together, we calculate that a “good” strategy could make $206 per day for 302 days – roughly $63k in a year.

Days in simulation

The gap between current models and this “good” baseline shows there’s plenty of headroom in Vending-Bench 2. Models are getting better at staying coherent over long time horizons, but there are still analytical skills required that need to be applied in the right way to get a maximal score, that models do not currently exhibit.