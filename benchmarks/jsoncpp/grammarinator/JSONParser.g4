/** Taken from "The Definitive ANTLR 4 Reference" by Terence Parr */

// Derived from https://json.org
// Extended to cover JsonCpp relaxed reader features:
// - C/C++ comments
// - trailing commas in objects and arrays
// - dropped null placeholders in arrays, e.g. [1,,3,]
// - numeric object keys
// - single-quoted strings
// - special floats: NaN, Infinity, -Infinity
// - optional UTF-8 BOM

// $antlr-format alignTrailingComments true, columnLimit 150, minEmptyLines 1, maxEmptyLinesToKeep 1, reflowComments false, useTab false
// $antlr-format allowShortRulesOnASingleLine false, allowShortBlocksOnASingleLine true, alignSemicolons hanging, alignColons hanging

parser grammar JSONParser;

options {  tokenVocab = JSONLexer; }

json
    : SETTING BOM? value EOF
    ;

obj
    : LBRACE pair (COMMA pair)* COMMA? RBRACE
    | LBRACE RBRACE
    ;

pair
    : key COLON value
    ;

key
    : STRING
    | SINGLE_QUOTED_STRING
    | NUMBER
    ;

arr
    : LBRACK RBRACK
    | LBRACK arrElement (COMMA arrElement)* COMMA? RBRACK
    | LBRACK COMMA arrElement (COMMA arrElement)* COMMA? RBRACK
    | LBRACK COMMA RBRACK
    ;

arrElement
    : value
    |
    ;

value
    : STRING
    | SINGLE_QUOTED_STRING
    | NUMBER
    | SPECIAL_FLOAT
    | obj
    | arr
    | TRUE
    | FALSE
    | NULL
    ;
