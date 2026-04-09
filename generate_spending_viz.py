import plotly.express as px
import polars as pl
from polars import col as C


def main():
    # Load data
    df = pl.read_csv("enriched_transactions.csv", infer_schema_length=None)

    # Create timestamp from booking_date and time_of_day
    df = df.with_columns(
        pl.format("{}T{}", C.booking_date, C.time_of_day).str.to_datetime().alias("timestamp")
    ).sort("timestamp")

    # Exclude "Excluded" to focus on real spending/income
    df = df.filter(~C.category.is_in(["Excluded", None]))

    # Group by timestamp and category, summing amounts
    ts_category_sums = (
        df.group_by(["timestamp", "category"])
        .agg(C.amount.sum().alias("tx_amount"))
        .sort(["category", "timestamp"])
    )

    # Calculate cumulative sum per category
    ts_category_sums = ts_category_sums.with_columns(
        C.tx_amount.cum_sum().over("category").alias("cumulative_amount")
    )

    # Join the original df back to get clean_name and counterparty for hover
    ts_category_details = ts_category_sums.join(
        df.select(
            ["timestamp", "category", "clean_name", "counterparty", "amount", "source"]
        ),
        on=["timestamp", "category"],
    ).sort(["category", "timestamp"])

    # Create the figure
    fig = px.line(
        ts_category_details,
        x="timestamp",
        y="cumulative_amount",
        color="category",
        line_shape="hv",
        hover_data=["clean_name", "counterparty", "amount", "source"],
        title="Cumulative Income and Spending by Category (AI Labels Highlighted)",
        labels={
            "cumulative_amount": "Total (£)",
            "timestamp": "Time",
            "clean_name": "Counterparty",
            "counterparty": "Raw Counterparty",
            "amount": "Amount",
            "source": "Label Source",
        },
        template="plotly_white",
    )

    # Add scatter points for AI_AGENT transactions
    ai_only = ts_category_details.filter(C.source == "AI_AGENT")
    if not ai_only.is_empty():
        ai_scatter = px.scatter(
            ai_only,
            x="timestamp",
            y="cumulative_amount",
            color="category",
            hover_data=["clean_name", "counterparty", "amount", "source"],
        )
        # Update markers to be distinct
        for trace in ai_scatter.data:
            trace.update(
                mode="markers",
                marker=dict(symbol="x", size=5),
                showlegend=False,
            )
            fig.add_trace(trace)

    # Save to HTML
    fig.write_html("spending_viz.html")

    print("Visualization saved to spending_viz.html")


if __name__ == "__main__":
    main()
