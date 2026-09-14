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

-- 4. What the file actually is. A .csv name does not make a file text: Excel will
--    happily save a workbook in binary form under that extension, and loading one
--    fills the table with what looks like random accented characters.
SELECT CASE
    WHEN hex(left(line, 2)) = '504B' THEN
        'ZIP container - this is an .xlsx/.xlsb workbook, not a csv. '
        'Open it in Excel and Save As "CSV UTF-8", then load with utf8mb4.'
    WHEN hex(left(line, 2)) = 'C390C38F' THEN
        'old .xls binary workbook, not a csv. '
        'Open it in Excel and Save As "CSV UTF-8", then load with utf8mb4.'
    WHEN hex(left(line, 2)) IN ('C3BFC3BE', 'C3BEC3BF') THEN
        'UTF-16 - MySQL cannot read it. Re-save as "CSV UTF-8".'
    WHEN hex(left(line, 3)) = 'C3AFC2BBC2BF' THEN
        'UTF-8 with a byte order mark - load with CHARACTER SET utf8mb4.'
    ELSE 'plain text - the line endings and separator above are what to go by.'
  END AS file_type
FROM   raw_probe
LIMIT  1;

SELECT hex(left(line, 24)) AS first_bytes, left(line, 100) AS first_line
FROM   raw_probe
LIMIT  2;

-- DROP TABLE raw_probe;
