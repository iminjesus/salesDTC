-- Product master, loaded from rawdata/product_2608.csv
--
-- The columns are exactly the columns of that file, in the same order, so
-- LOAD DATA needs no column list. Each comment is the original header.
--
-- utf8mb4 matters here: descriptions carry characters such as the trademark
-- sign in "Slim S-pen(TM) Case".

USE sales_2526;

DROP TABLE IF EXISTS product;

CREATE TABLE product (
    sku             varchar(40)  NOT NULL         COMMENT 'SKU',
    division        varchar(10)                   COMMENT 'Division',
    category        varchar(60)                   COMMENT 'Category',
    product_range   varchar(120)                  COMMENT 'Range',
    description     varchar(150)                  COMMENT 'Description',
    product_grp     varchar(20)                   COMMENT 'Product Grp',
    product         varchar(40)                   COMMENT 'Product',
    marketing_name  varchar(80)                   COMMENT 'Marketing Name',
    series          varchar(40)                   COMMENT 'Series',
    colour          varchar(40)                   COMMENT 'Colour',
    ram_storage     varchar(30)                   COMMENT 'Ram_Storage',
    current_range   varchar(5)                    COMMENT 'Current Range',
    hybris_status   varchar(20)                   COMMENT 'Hybris Status',
    eol_status      varchar(20)                   COMMENT 'EOL Status',
    estore_price    decimal(12,2)                 COMMENT 'Estore Price',

    PRIMARY KEY (sku),
    KEY ix_product_division (division),
    KEY ix_product_category (category, product_range),
    KEY ix_product_series   (series)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Product master keyed by SKU.';

-- "Range" is a reserved word in MySQL, so that column is product_range.
--
-- Load it yourself, e.g.
--
-- LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/salesDTC/rawdata/product_2608.csv'
--     INTO TABLE product
--     CHARACTER SET utf8mb4        -- error 1300 -> the file is Windows ANSI: use euckr
--     FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
--     LINES TERMINATED BY '\r\n'
--     IGNORE 1 LINES;
--
-- SELECT count(*) FROM product;
-- SHOW WARNINGS;
