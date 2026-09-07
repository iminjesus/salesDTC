-- File probe: run this first when a load fails and you are not sure what the
-- file actually looks like. It reads whole lines, splitting nothing.
--
-- How to read the result:
--   lines_read = 1        -> the line ending is wrong. The file is probably LF
--                           only, so use LINES TERMINATED BY '\n'.
--   comma_fields ~ 251    -> comma separated, keep FIELDS TERMINATED BY ','
--                           (a few more is fine: quoted values like "1,268.93"
--                            carry commas of their own)
--   tab_fields   = 251    -> tab separated, use FIELDS TERMINATED BY '\t'
--   garbled Korean in head -> wrong CHARACTER SET (try euckr)
--
-- Change CHARACTER SET / LINES TERMINATED BY here the same way as in the load.

USE sales_2526;

DROP TABLE IF EXISTS raw_probe;
CREATE TABLE raw_probe (line text) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/salesDTC/rawdata/sales_2526.csv'
    INTO TABLE raw_probe
    CHARACTER SET utf8mb4
    FIELDS TERMINATED BY '\0' ESCAPED BY ''    -- split nothing
    LINES TERMINATED BY '\r\n';

SELECT count(*) AS lines_read FROM raw_probe;

SELECT CHAR_LENGTH(line)                                        AS len,
       CHAR_LENGTH(line) - CHAR_LENGTH(REPLACE(line, ',',  '')) + 1 AS comma_fields,
       CHAR_LENGTH(line) - CHAR_LENGTH(REPLACE(line, '\t', '')) + 1 AS tab_fields,
       LEFT(line, 120)                                          AS head
FROM   raw_probe
LIMIT  3;

-- DROP TABLE raw_probe;
