# 返回与显示：函数算出了结果，谁能拿到它？

本讲义为 MindOS 原创公开教学材料，内容状态：待教师／助教审核。先修：函数定义与调用。

## 从一个真实需求出发

你写了一个计算费用的函数，下一步还要把结果乘以人数。此时“把数字显示给人看”不够，后续代码必须**取得这个数字**。`return` 和 `print` 的差别就在这里：`return` 把值交还给调用者；`print` 主要把内容写到输出中。屏幕显示了某个数字，并不表示调用表达式的值就是它。

## 跟着调用过程看 return

```python
def add_fee(price, fee):
    total = price + fee
    return total

bill = add_fee(20, 3)
final_bill = bill * 2
```

执行 `add_fee(20, 3)` 时，`price` 是 `20`，`fee` 是 `3`，`total` 得到 `23`。遇到 `return total`，函数结束本次调用，把 `23` 放回调用表达式所在的位置。因此 `bill` 是 `23`，`final_bill` 是 `46`。你可以把调用表达式暂时替换成它的返回值来检查：`bill = add_fee(20, 3)` 的效果是让 `bill` 接收 `23`。

## 把 return 换成 print 会怎样

```python
def show_fee(price, fee):
    total = price + fee
    print(total)

bill = show_fee(20, 3)
```

这次屏幕会显示 `23`。但函数没有执行 `return`，运行到函数体末尾时，这次调用的结果是 `None`，所以 `bill` 是 `None`，不是 `23`。如果再写 `bill * 2`，就无法像数值那样继续计算。问题不是“没有算出 23”，而是“没有把 23 交给调用者”。

## 显示和返回可以同时发生

```python
def report_fee(price, fee):
    total = price + fee
    print("本次费用：", total)
    return total

bill = report_fee(20, 3)
```

这个函数先显示费用，再返回 `23`。因此屏幕有文字，`bill` 也有可继续计算的数字。`print` 和 `return` 不互斥，作用却不同。设计函数时先问：调用者后续是否需要使用结果？如果需要，就要返回它；显示信息是另一项选择。

## return 还会结束本次调用

```python
def classify(score):
    if score >= 60:
        return "通过"
    return "继续练习"
```

当 `score` 为 `75`，第一个 `return` 把 `"通过"` 交给调用者，此次调用就结束，不会继续执行下面的 `return`。当 `score` 为 `45`，条件不成立，执行第二个 `return`。这解释了为什么 `return` 不只是“给一个值”，还控制函数在哪里结束。

如果只写 `return` 而不写表达式，也会返回 `None`。如果始终没有执行到任何 `return`，运行到函数体末尾也返回 `None`。`None` 不是数字 `0`，也不是字符串 `"None"`。

## 常见误区与自查方法

- 误区：“屏幕显示 23，所以变量 bill 是 23。”应分别追踪**输出**和**调用表达式的值**。
- 误区：“在函数内算出了 total，外面就可以直接用 total。”函数内的局部名字不会因此自动变成调用者的结果；应显式返回所需值。
- 误区：“return 之后的同一次调用还会继续向下运行。”执行到 `return` 时，这次调用已经结束。
- 自查：画两栏，一栏写屏幕显示了什么，另一栏写调用表达式返回了什么；再看变量实际接收了哪一栏。

## 换一个例子检验理解

```python
def triple(number):
    print("正在计算")
    return number * 3

answer = triple(4)
```

这段代码会显示“正在计算”，但不会自动显示 `12`；`answer` 得到 `12`。如果再执行 `print(answer)`，屏幕才会另外显示 `12`。能分清这三步，就能在更复杂的函数里避免把输出和返回混为一谈。

语法事实可对照 [Python 官方教程：定义函数](https://docs.python.org/zh-cn/3/tutorial/controlflow.html#defining-functions)和 [Python 官方文档：print](https://docs.python.org/zh-cn/3/library/functions.html#print)。本材料与公开练习配套，不用于正式学习效果评估。
