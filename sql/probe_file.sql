-- Look at the raw file before loading it: how many lines, where they end, what
-- separates the fields, and how it is encoded. Nothing is split here, so the
-- answers do not depend on the settings being right already.
--
-- Point the path at whichever file is misbehaving, run the whole script, and read
-- the results from the bottom up.

USE sales_2526;

DROP TABLE IF EXISTS raw_probe;
CREATE TABLE raw_probe (line varchar(4000)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Split on newline only, never on \r\n, so a file that uses either still comes
-- through one row per line.
LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/salesDTC/rawdata/customer_2608.csv'
    INTO TABLE raw_probe
    CHARACTER SET latin1
    FIELDS TERMINATED BY '\0' ESCAPED BY ''
    LINES TERMINATED BY '\n';

-- 1. Lines read. If this is 1, or far fewer than the rows you expect, the file
--    does not use \n at all - it is an old-style \r only file, and LINES
--    TERMINATED BY '\r' is what the load needs.
SELECT count(*) AS lines_read FROM raw_probe;

-- 2. Line endings. crlf_lines should be either 0 or the whole file.
--      all CRLF -> LINES TERMINATED BY '\r\n'
--      all LF   -> LINES TERMINATED BY '\n'
SELECT sum(line LIKE '%\r') AS crlf_lines,
       sum(line NOT LIKE '%\r') AS lf_lines
FROM   raw_probe;

-- 3. Field separator: whichever count is one less than your column count wins.
--    customer has 7 columns, product has 15.
SELECT char_length(line)                                        AS first_line_len,
       char_length(line) - char_length(REPLACE(line, ',',  '')) AS commas,
       char_length(line) - char_length(REPLACE(line, '\t', '')) AS tabs,
       char_length(line) - char_length(REPLACE(line, ';',  '')) AS semicolons,
       char_length(line) - char_length(REPLACE(line, '|',  '')) AS pipes
FROM   raw_probe
LIMIT  3;

-- 4. Encoding. Look at the start of the header line:
--      "53 6F 6C 64..."        plain ASCII, fine
--      "EF BB BF ..."          UTF-8 with a BOM - load as utf8mb4
--      "FF FE" then 00 between every character  UTF-16: re-save it as CSV UTF-8,
--                                               MySQL cannot read UTF-16 here
SELECT hex(left(line, 24)) AS first_bytes, left(line, 100) AS first_line
FROM   raw_probe
LIMIT  2;

-- DROP TABLE raw_probe;
