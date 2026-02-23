/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2014 by Bart Kiers (original author) and Alexandre Vitorelli (contributor -> ported to CSharp)
 * Copyright (c) 2017-2020 by Ivan Kochurkin (Positive Technologies):
    added ECMAScript 6 support, cleared and transformed to the universal grammar.
 * Copyright (c) 2018 by Juan Alvarez (contributor -> ported to Go)
 * Copyright (c) 2019 by Student Main (contributor -> ES2020)
 *
 * Permission is hereby granted, free of charge, to any person
 * obtaining a copy of this software and associated documentation
 * files (the "Software"), to deal in the Software without
 * restriction, including without limitation the rights to use,
 * copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following
 * conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
 * OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
 * NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
 * WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 * OTHER DEALINGS IN THE SOFTWARE.
 */

// $antlr-format alignTrailingComments true, columnLimit 150, minEmptyLines 1, maxEmptyLinesToKeep 1, reflowComments false, useTab false
// $antlr-format allowShortRulesOnASingleLine false, allowShortBlocksOnASingleLine true, alignSemicolons hanging, alignColons hanging

parser grammar JavaScriptParser;

// Insert here @header for C++ parser.

options {
    tokenVocab = JavaScriptLexer;
    superClass = JavaScriptParserBase;
}

program
    : /*HashBangLine?*/ sourceElements EOF
    ;

sourceElement
    : statement
    | importStatement
    | exportStatement
    ;

statement
    : block
    | variableStatement
    | emptyStatement_
    | classDeclaration
    | functionDeclaration
    | expressionStatement
    | ifStatement
    | iterationStatement
    | continueStatement
    | breakStatement
    | returnStatement
    | withStatement
    | labelledStatement
    | switchStatement
    | throwStatement
    | tryStatement
    | debuggerStatement
    ;

block
    : '{' statementList? '}'
    ;

statementList
    : statement+
    ;

importStatement
    : Import importFromBlock
    ;

importFromBlock
    : importDefault importFrom eos
    | importDefault ',' importNamespace importFrom eos
    | importDefault ',' importModuleItems importFrom eos
    | importNamespace importFrom eos
    | importModuleItems importFrom eos
    | StringLiteral eos
    ;

importModuleItems
    : '{' (importAliasName ',')* (importAliasName ','?)? '}'
    ;

importAliasName
    : moduleExportName (As importedBinding)?
    ;

moduleExportName
    : identifierName
    | StringLiteral
    ;

// yield and await are permitted as BindingIdentifier in the grammar
importedBinding
    : Identifier
    | Yield
    | Await
    ;

importDefault
    : importedBinding
    ;

importNamespace
    : '*' As importedBinding
    ;

importFrom
    : From StringLiteral
    ;

aliasName
    : identifierName (As identifierName)?
    ;

exportStatement
    : Export Default functionDeclaration  # ExportDefaultFunctionDeclaration
    | Export Default classDeclaration     # ExportDefaultClassDeclaration
    | Export Default singleExpression eos # ExportDefaultExpression
    | Export exportFromBlock              # ExportFromDeclaration
    | Export variableStatement            # ExportVariableStatement
    | Export classDeclaration             # ExportClassDeclaration
    | Export functionDeclaration          # ExportFunctionDeclaration
    ;

exportFromBlock
    : importNamespace importFrom eos
    | exportModuleItems importFrom? eos
    ;

exportModuleItems
    : '{' (exportAliasName ',')* (exportAliasName ','?)? '}'
    ;

exportAliasName
    : moduleExportName (As moduleExportName)?
    ;

declaration
    : variableStatement
    | classDeclaration
    | functionDeclaration
    ;

variableStatement
    : Var variableDeclaration (',' variableDeclaration)* eos
    | let_ letBinding (',' letBinding)* eos
    | Const constBinding (',' constBinding)* eos
    ;

variableDeclarationList
    : Var variableDeclaration (',' variableDeclaration)*
    | let_ letBinding (',' letBinding)*
    | Const constBinding (',' constBinding)*
    ;

variableDeclaration
    : bindingIdentifier initializer?
    | bindingPattern initializer
    ;

letBinding
    : bindingIdentifier initializer?
    | bindingPattern initializer
    ;

constBinding
    : bindingIdentifier initializer
    | bindingPattern initializer
    ;

emptyStatement_
    : SemiColon
    ;

expressionStatement
    : {self.notOpenBraceAndNotFunction()}? expressionSequence eos
    ;

ifStatement
    : If '(' expressionSequence ')' statement (Else statement)?
    ;

iterationStatement
    : Do statement While '(' expressionSequence ')' eos                                                                     # DoStatement
    | While '(' expressionSequence ')' statement                                                                            # WhileStatement
    | For '(' (expressionSequence | variableDeclarationList)? ';' expressionSequence? ';' expressionSequence? ')' statement # ForStatement
    | For '(' (singleExpression | forDeclaration) In expressionSequence ')' statement                                       # ForInStatement
    | For Await? '(' (singleExpression | forDeclaration) Of expressionSequence ')' statement                                # ForOfStatement
    ;

forDeclaration
    : Var forBinding
    | let_ forBinding
    | Const forBinding
    ;

forBinding
    : bindingIdentifier
    | bindingPattern
    ;

varModifier // let, const - ECMAScript 6
    : Var
    | let_
    | Const
    ;

continueStatement
    : Continue ({self.notLineTerminator()}? identifier)? eos
    ;

breakStatement
    : Break ({self.notLineTerminator()}? identifier)? eos
    ;

returnStatement
    : Return ({self.notLineTerminator()}? expressionSequence)? eos
    ;

withStatement
    : With '(' expressionSequence ')' statement
    ;

switchStatement
    : Switch '(' expressionSequence ')' caseBlock
    ;

caseBlock
    : '{' caseClauses? (defaultClause caseClauses?)? '}'
    ;

caseClauses
    : caseClause+
    ;

caseClause
    : Case expressionSequence ':' statementList?
    ;

defaultClause
    : Default ':' statementList?
    ;

labelledStatement
    : identifier ':' statement
    ;

throwStatement
    : Throw {self.notLineTerminator()}? expressionSequence eos
    ;

tryStatement
    : Try block (catchProduction finallyProduction? | finallyProduction)
    ;

catchProduction
    : Catch ('(' catchParameter ')')? block
    ;

catchParameter
    : bindingIdentifier
    | bindingPattern
    ;

finallyProduction
    : Finally block
    ;

debuggerStatement
    : Debugger eos
    ;

functionDeclaration
    : Async? Function_ '*'? identifier '(' formalParameterList? ')' functionBody
    ;

classDeclaration
    : Class identifier classTail
    ;

classTail
    : (Extends singleExpression)? '{' classElement* '}'
    ;

classElement
    : (Static | {self.n("static")}? identifier)? methodDefinition
    | (Static | {self.n("static")}? identifier)? fieldDefinition
    | (Static | {self.n("static")}? identifier) block
    | emptyStatement_
    ;

methodDefinition
    : (Async {self.notLineTerminator()}?)? '*'? classElementName '(' formalParameterList? ')' functionBody
    | getter '(' ')' functionBody
    | setter '(' setterParameter ')' functionBody
    ;

setterParameter
    : bindingElement
    ;

fieldDefinition
    : classElementName initializer?
    ;

classElementName
    : propertyName
    | privateIdentifier
    ;

privateIdentifier
    : '#' identifierName
    ;

formalParameterList
    : formalParameterArg (',' formalParameterArg)* (',' lastFormalParameterArg)?
    | lastFormalParameterArg
    ;

formalParameterArg
    : bindingElement
    ;

lastFormalParameterArg // ECMAScript 6: Rest Parameter
    : Ellipsis bindingRestElement
    ;

functionBody
    : '{' sourceElements? '}'
    ;

sourceElements
    : sourceElement+
    ;

arrayLiteral
    : ('[' elementList ']')
    ;

// JavaScript supports arrasys like [,,1,2,,].
elementList
    : ','* arrayElement? (','+ arrayElement) * ','* // Yes, everything is optional
    ;

arrayElement
    : Ellipsis? singleExpression
    ;

propertyAssignment
    : propertyName ':' singleExpression                                  # PropertyExpressionAssignment
    | '[' singleExpression ']' ':' singleExpression                      # ComputedPropertyExpressionAssignment
    | Async? '*'? propertyName '(' formalParameterList? ')' functionBody # FunctionProperty
    | getter '(' ')' functionBody                                        # PropertyGetter
    | setter '(' setterParameter ')' functionBody                        # PropertySetter
    | Ellipsis singleExpression                                          # SpreadProperty
    | identifierReference                                                # PropertyShorthand
    ;

propertyName
    : identifierName
    | StringLiteral
    | numericLiteral
    | '[' singleExpression ']'
    ;

arguments
    : '(' (argument (',' argument)* ','?)? ')'
    ;

argument
    : Ellipsis? singleExpression
    ;

expressionSequence
    : singleExpression (',' singleExpression)*
    ;

singleExpression
    : anonymousFunction                                 # AnonymusFunctionExpression  // 0
    | Class identifier? classTail                       # ClassExpression  // 1
    | singleExpression '?.' singleExpression            # OptionalChainExpression  // 2
    | singleExpression '?.'? '[' expressionSequence ']' # MemberIndexExpression  // 3
    | singleExpression '?'? '.' '#'? identifierName     # MemberDotExpression  // 4
    // Split to try `new Date()` first, then `new Date`.
    | New identifier arguments                                             # NewExpression  // 5
    | New singleExpression arguments                                       # NewExpression  // 6
    | New singleExpression                                                 # NewExpression  // 7
    | singleExpression arguments                                           # ArgumentsExpression  // 8
    | New '.' identifier                                                   # MetaExpression // new.target
    | singleExpression {self.notLineTerminator()}? '++'                    # PostIncrementExpression
    | singleExpression {self.notLineTerminator()}? '--'                    # PostDecreaseExpression
    | Delete singleExpression                                              # DeleteExpression
    | Void singleExpression                                                # VoidExpression
    | Typeof singleExpression                                              # TypeofExpression
    | '++' singleExpression                                                # PreIncrementExpression
    | '--' singleExpression                                                # PreDecreaseExpression
    | '+' singleExpression                                                 # UnaryPlusExpression
    | '-' singleExpression                                                 # UnaryMinusExpression
    | '~' singleExpression                                                 # BitNotExpression
    | '!' singleExpression                                                 # NotExpression
    | Await singleExpression                                               # AwaitExpression
    | <assoc = right> singleExpression '**' singleExpression               # PowerExpression
    | singleExpression ('*' | '/' | '%') singleExpression                  # MultiplicativeExpression
    | singleExpression ('+' | '-') singleExpression                        # AdditiveExpression  // 24
    | <assoc = right> singleExpression '??' singleExpression               # CoalesceExpression
    | singleExpression ('<<' | '>>' | '>>>') singleExpression              # BitShiftExpression
    | singleExpression ('<' | '>' | '<=' | '>=') singleExpression          # RelationalExpression
    | singleExpression Instanceof singleExpression                         # InstanceofExpression
    | singleExpression In singleExpression                                 # InExpression
    | singleExpression ('==' | '!=' | '===' | '!==') singleExpression      # EqualityExpression
    | singleExpression '&' singleExpression                                # BitAndExpression
    | singleExpression '^' singleExpression                                # BitXOrExpression
    | singleExpression '|' singleExpression                                # BitOrExpression
    | singleExpression '&&' singleExpression                               # LogicalAndExpression
    | singleExpression '||' singleExpression                               # LogicalOrExpression
    | singleExpression '?' singleExpression ':' singleExpression           # TernaryExpression
    | <assoc = right> singleExpression '=' singleExpression                # AssignmentExpression
    | <assoc = right> singleExpression assignmentOperator singleExpression # AssignmentOperatorExpression
    | Import '(' singleExpression ')'                                      # ImportExpression
    | singleExpression templateStringLiteral                               # TemplateStringExpression // ECMAScript 6
//    | yieldStatement                                                       # YieldExpression          // ECMAScript 6
    | (Yield | YieldStar) ({self.notLineTerminator()}? expressionSequence)? # YieldExpression
    | This                                                                 # ThisExpression
    | identifier                                                           # IdentifierExpression  // 43
    | Super                                                                # SuperExpression
    | literal                                                              # LiteralExpression
    | arrayLiteral                                                         # ArrayLiteralExpression
    | objectLiteral                                                        # ObjectLiteralExpression
    | '(' expressionSequence ')'                                           # ParenthesizedExpression
    ;

initializer
    // TODO: must be `= AssignmentExpression` and we have such label alredy but it doesn't respect the specification.
    //  See https://tc39.es/ecma262/multipage/ecmascript-language-expressions.html#prod-Initializer
    : '=' singleExpression
    ;

bindingIdentifier
    : identifier
    ;

identifierReference
    : identifier
    ;

bindingPattern
    : objectBindingPattern
    | arrayBindingPattern
    ;

bindingElement
    : bindingIdentifier initializer?
    | bindingPattern initializer?
    ;

bindingRestElement
    : bindingIdentifier
    | bindingPattern
    ;

objectBindingPattern
    : '{' (bindingPropertyList (',' bindingRestProperty)? ','? | bindingRestProperty)? '}'
    ;

bindingPropertyList
    : bindingProperty (',' bindingProperty)*
    ;

bindingProperty
    : bindingIdentifier
    | propertyName ':' bindingElement
    ;

bindingRestProperty
    : Ellipsis bindingIdentifier
    ;

arrayBindingPattern
    : '[' arrayBindingElements? arrayBindingRestElement? ']'
    ;

arrayBindingElements
    : ','* arrayBindingElement? (','+ arrayBindingElement)* ','*
    ;

arrayBindingElement
    : bindingElement
    ;

arrayBindingRestElement
    : Ellipsis bindingRestElement
    ;

objectLiteral
    : '{' (propertyAssignment (',' propertyAssignment)* ','?)? '}'
    ;

functionExpression
    : Async? Function_ '*'? identifier? '(' formalParameterList? ')' functionBody
    ;

anonymousFunction
    : functionExpression                                    # FunctionExpressionDecl
    | Async? arrowFunctionParameters '=>' arrowFunctionBody # ArrowFunction
    ;

arrowFunctionParameters
    : identifier
    | '(' formalParameterList? ')'
    ;

arrowFunctionBody
    : singleExpression
    | functionBody
    ;

assignmentOperator
    : '*='
    | '/='
    | '%='
    | '+='
    | '-='
    | '<<='
    | '>>='
    | '>>>='
    | '&='
    | '^='
    | '|='
    | '**='
    | '??='
    ;

literal
    : NullLiteral
    | BooleanLiteral
    | StringLiteral
    | templateStringLiteral
    | RegularExpressionLiteral
    | numericLiteral
    | bigintLiteral
    ;

templateStringLiteral
    : BackTick templateStringAtom* BackTick
    ;

templateStringAtom
    : TemplateStringAtom
    | TemplateStringStartExpression expressionSequence /* singleExpression */
     TemplateCloseBrace
    ;

numericLiteral
    : DecimalLiteral
    | HexIntegerLiteral
    | OctalIntegerLiteral
    | OctalIntegerLiteral2
    | BinaryIntegerLiteral
    ;

bigintLiteral
    : BigDecimalIntegerLiteral
    | BigDecimalLiteral
    | BigHexIntegerLiteral
    | BigHexFloatLiteral
    | BigOctalIntegerLiteral
    | BigBinaryIntegerLiteral
    | BigFloatLiteral
    ;

getter
    : {self.n("get")}? identifier classElementName
    ;

setter
    : {self.n("set")}? identifier classElementName
    ;

identifierName
    : identifier
    | reservedWord
    ;

identifier
    : Identifier
    | NonStrictLet
    | Async
    | As
    | From
    | Yield
    | Of
    ;

reservedWord
    : keyword
    | NullLiteral
    | BooleanLiteral
    ;

keyword
    : Break
    | Do
    | Instanceof
    | Typeof
    | Case
    | Else
    | New
    | Var
    | Catch
    | Finally
    | Return
    | Void
    | Continue
    | For
    | Switch
    | While
    | Debugger
    | Function_
    | This
    | With
    | Default
    | If
    | Throw
    | Delete
    | In
    | Try
    | Class
    | Enum
    | Extends
    | Super
    | Const
    | Export
    | Import
    | Implements
    | let_
    | Private
    | Public
    | Interface
    | Package
    | Protected
    | Static
    | Yield
    | YieldStar
    | Async
    | Await
    | From
    | As
    | Of
    ;

let_
    : NonStrictLet
    | StrictLet
    ;

eos
    : SemiColon
    | EOF
    | {self.lineTerminatorAhead()}?
    | {self.closeBrace()}?
    ;
