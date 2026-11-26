-- Reference definition of the two models every recipe builds, used to compute
-- expected/. Each tool reimplements exactly this.
CREATE OR REPLACE TABLE customers AS SELECT * FROM read_csv('data/customers.csv');
CREATE OR REPLACE TABLE orders AS SELECT * FROM read_csv('data/orders.csv');
CREATE OR REPLACE TABLE order_items AS SELECT * FROM read_csv('data/order_items.csv',
    types = {'unit_price': 'DECIMAL(10,2)'});

CREATE OR REPLACE TABLE order_totals AS
SELECT o.order_id, o.customer_id, o.order_date,
       CAST(sum(i.quantity * i.unit_price) AS DECIMAL(12,2)) AS order_total
FROM orders o JOIN order_items i USING (order_id)
GROUP BY ALL;

CREATE OR REPLACE TABLE customers_enriched AS
SELECT c.customer_id, c.name, c.country,
       count(t.order_id) AS order_count,
       CAST(coalesce(sum(t.order_total), 0) AS DECIMAL(12,2)) AS lifetime_value
FROM customers c LEFT JOIN order_totals t USING (customer_id)
GROUP BY ALL;

CREATE OR REPLACE TABLE daily_revenue AS
SELECT order_date, CAST(sum(order_total) AS DECIMAL(12,2)) AS revenue
FROM order_totals
GROUP BY ALL;
