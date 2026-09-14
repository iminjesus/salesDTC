-- Customer master, loaded from rawdata/customer_2608.csv
--
-- The columns are exactly the columns of that file, in the same order, so
-- LOAD DATA needs no column list. Each comment is the original header.

USE sales_2526;

DROP TABLE IF EXISTS customer;

CREATE TABLE customer (
    sold_to        varchar(20)  NOT NULL          COMMENT 'Sold-To',
    account_name   varchar(50)                    COMMENT 'Account Name',
    description    varchar(150)                   COMMENT 'Description',
    dist_channel   varchar(5)                     COMMENT 'Dist Channel',
    customer_type  varchar(20)                    COMMENT 'Type',
    portal_group   varchar(30)                    COMMENT 'Portal Group',
    neilson_type   varchar(10)                    COMMENT 'Neilson Type',

    PRIMARY KEY (sold_to),
    KEY ix_customer_type   (customer_type),
    KEY ix_customer_portal (portal_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='Customer master keyed by SAP Sold-To.';

-- Load it yourself, e.g.
--
-- LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/salesDTC/rawdata/customer_2608.csv'
--     INTO TABLE customer
--     CHARACTER SET utf8mb4        -- error 1300 -> the file is Windows ANSI: use euckr
--     FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
--     LINES TERMINATED BY '\r\n'
--     IGNORE 1 LINES;
--
-- SELECT count(*) FROM customer;
-- SHOW WARNINGS;
