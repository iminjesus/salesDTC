-- Load the two master files. Run sql/customer.sql and sql/product.sql first.
--
-- Before running:
--   * Workbench connection > Advanced > Others must contain OPT_LOCAL_INFILE=1,
--     otherwise the load fails with error 3948. Reconnect after setting it.
--   * Close the CSVs in Excel.
--   * Use forward slashes in the paths; a backslash is an escape character.
--
-- CHARACTER SET must match how the file was written. Excel's plain
-- "CSV (Comma delimited)" is the Windows code page, not UTF-8:
--
--   latin1    Excel ANSI on a Western Windows. MySQL's latin1 is really
--             Windows-1252, so (TM), en dash and (R) come through correctly.
--   euckr     Windows ANSI on a Korean system, i.e. a file with Hangul in it.
--   utf8mb4   the file was saved from Excel as "CSV UTF-8".
--
-- The wrong one shows up as error 1300, or as mangled characters in the
-- description column. The last query in this script counts those.
--
-- For a tab-separated file, change the FIELDS line to:
--     FIELDS TERMINATED BY '\t' ESCAPED BY ''

SET GLOBAL local_infile = 1;

USE sales_2526;

-- == customer ========
TRUNCATE TABLE customer;

LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/salesDTC/rawdata/customer_2608.csv'
    INTO TABLE customer
    CHARACTER SET latin1
    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
    LINES TERMINATED BY '\r\n'
    IGNORE 1 LINES;

SELECT count(*) AS customer_rows FROM customer;
SHOW WARNINGS;

-- == product ========
TRUNCATE TABLE product;

LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/salesDTC/rawdata/product_2608.csv'
    INTO TABLE product
    CHARACTER SET latin1
    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
    LINES TERMINATED BY '\r\n'
    IGNORE 1 LINES;

SELECT count(*) AS product_rows FROM product;
SHOW WARNINGS;

-- == check ========
-- Row counts must match the files (their line count minus the header). A lower
-- number means rows were skipped - under LOAD DATA LOCAL a duplicate primary key
-- is only a warning, so check SHOW WARNINGS above rather than assuming.

SELECT sold_to, account_name, description, dist_channel,
       customer_type, portal_group, neilson_type
FROM   customer
ORDER  BY sold_to
LIMIT  5;

SELECT sku, division, category, product_range, description,
       colour, current_range, eol_status, estore_price
FROM   product
ORDER  BY sku
LIMIT  5;

-- Anything that did not land as a number shows up here.
SELECT count(*) AS products_without_price FROM product WHERE estore_price IS NULL;

-- Products whose description lost its special characters would show as '?' here.
SELECT count(*) AS descriptions_with_symbols
FROM   product
WHERE  description REGEXP '[^ -~]';
