import plotly.express as px
import polars as pl


def main():
    # Load data
    df = pl.read_csv("enriched_transactions.csv", infer_schema_length=None)

    # Create timestamp from booking_date and time_of_day
    df = df.with_columns(
        pl.format("{}T{}", pl.col("booking_date"), pl.col("time_of_day"))
        .str.to_datetime()
        .alias("timestamp")
    ).sort("timestamp")

    # Exclude "Excluded" to focus on real spending/income
    df = df.filter(~pl.col("category").is_in(["Excluded", None]))

    # Group by timestamp and category, summing amounts
    ts_category_sums = (
        df.group_by(["timestamp", "category"])
        .agg(pl.col("amount").sum().alias("tx_amount"))
        .sort(["category", "timestamp"])
    )

    # Calculate cumulative sum per category
    ts_category_sums = ts_category_sums.with_columns(
        pl.col("tx_amount").cum_sum().over("category").alias("cumulative_amount")
    )

    # Join the original df back to get clean_name and counterparty for hover
    ts_category_details = ts_category_sums.join(
        df.select(["timestamp", "category", "clean_name", "counterparty", "amount"]),
        on=["timestamp", "category"],
    ).sort(["category", "timestamp"])

    # Create the figure
    fig = px.line(
        ts_category_details.to_pandas(),
        x="timestamp",
        y="cumulative_amount",
        color="category",
        line_shape="hv",
        hover_data=["clean_name", "counterparty", "amount"],
        title="Cumulative Income and Spending by Category",
        labels={
            "cumulative_amount": "Total (£)",
            "timestamp": "Time",
            "clean_name": "Counterparty",
            "counterparty": "Raw Counterparty",
            "amount": "Amount",
        },
        template="plotly_white",
    )

    # Save to HTML
    fig.write_html("spending_viz.html")

    print("Visualization saved to spending_viz.html")

    print("Visualizations saved to spending_viz.html")


if __name__ == "__main__":
    main()
