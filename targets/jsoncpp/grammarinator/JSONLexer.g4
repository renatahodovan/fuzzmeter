lexer grammar JSONLexer;

SETTING
    : . . . . -> pushMode(JSON)
    ;

mode JSON;

LBRACE
    : '{'
    ;

RBRACE
    : '}'
    ;

LBRACK
    : '['
    ;

RBRACK
    : ']'
    ;

COMMA
    : ','
    ;

COLON
    : ':'
    ;

TRUE
    : 'true'
    ;

FALSE
    : 'false'
    ;

NULL
    : 'null'
    ;

STRING
    : '"' (ESC | SAFECODEPOINT)* '"'
    ;

SINGLE_QUOTED_STRING
    : '\'' (ESC | SINGLE_QUOTED_SAFECODEPOINT)* '\''
    ;

fragment ESC
    : '\\' (["'\\/bfnrt] | UNICODE)
    ;

fragment UNICODE
    : 'u' HEX HEX HEX HEX
    ;

fragment HEX
    : [0-9a-fA-F]
    ;

fragment SAFECODEPOINT
    : ~ ["\\\u0000-\u001F]
    ;

fragment SINGLE_QUOTED_SAFECODEPOINT
    : ~ ['\\\u0000-\u001F]
    ;

SPECIAL_FLOAT
    : '-'? ('NaN' | 'Infinity')
    ;

NUMBER
    : '-'? INT ('.' [0-9]+)? EXP?
    ;

fragment INT
    // integer part forbids leading 0s (e.g. `01`)
    : '0'
    | [1-9] [0-9]*
    ;

// no leading zeros

fragment EXP
    // exponent number permits leading 0s (e.g. `1e01`)
    : [Ee] [+-]? [0-9]+
    ;

LINE_COMMENT
    : '//' ~[\r\n]* -> skip
    ;

BLOCK_COMMENT
    : '/*' .*? '*/' -> skip
    ;

BOM
    : '\uFEFF'
    ;

WS
    : [ \t\n\r]+ -> skip
    ;
