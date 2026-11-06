# Sample data

`customers.csv` has 55 rows of made-up customers (all `@example.com`, fictional) across five behavior types: champions, loyal, new, at risk and lapsed. Three rows are second accounts that share a phone number with an existing customer, so importing it also demonstrates merging (52 people from 55 rows).

Try it: open **CDP > Import Data**, choose this file, click **Import**, then **Score customers**. Or:

```bash
curl -X POST localhost:8000/ingest/csv -H "Content-Type: text/csv" --data-binary @sample-data/customers.csv
curl -X POST localhost:8000/models/run -H "Content-Type: application/json" -d '{}'
```
