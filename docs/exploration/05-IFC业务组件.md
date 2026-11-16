# 05 IFC 业务组件（DOM 与操作）

## 覆盖范围与方法

- 源码根 `ifc-6.5-react-webapp/`，下文路径均相对仓根；全部为只读阅读，未运行页面，DOM 结论来自 JSX，未经浏览器实测。
- 定位方式：`rg "type: '<Type>'"`。9 个 type 全部在 `osp-react-department-webcomps/src/ui/` 下找到，其他包（ifc-react-comps、designer-procomps、pubcomps）未出现同名 type。

| type | 源码（staticMembers 行） | 渲染实体 |
|---|---|---|
| PaymentUnit | `osp-react-department-webcomps/src/ui/field/PaymentUnit/index.tsx:632`，渲染 `.../PaymentUnit/components/PaymentUnit.jsx` | `@panui/fi` PacketClassify |
| InterestRateInput | `.../ui/field/InterestRateInput/index.tsx:766`（渲染也在此文件 `:571`） | antd `Input` |
| AccountOpenOrgan | `.../ui/field/AccountOpenOrgan/index.tsx:74` | PanuiHelpComp -> `@panui/fi` ParallelCode |
| PaymentAccount | `.../ui/field/PaymentAccount/index.tsx:72` | 同上 |
| CountryArea | `.../ui/field/CountryArea/index.tsx:74` | 同上 |
| Currency | `.../ui/base/Currency/index.tsx:1027` | `CurrencyCompent`（自定义下拉列表，内部 `SelectContain`） |
| AmountComp | `.../ui/base/AmountComp/index.tsx:586`，渲染 `.../AmountComp/components/AmountComp.jsx` | Currency + antd `Input` |
| PriceInput | `.../ui/field/PriceInput/register.tsx:16`，类 `index.tsx:8`，渲染 `.../PriceInput/components/PriceInput.jsx` | antd `Select` + `Input` |
| FormRadio | `.../ui/base/DepFormRadio/index.tsx:264` | antd `Radio.Group` |

`osp-react-department-webcomps/` 下的相对路径省略前缀 `.../`，即 `ui/` 在 `osp-react-department-webcomps/src/` 下。

### 公共约定

- compMark：`osp-client-app/src/config/RegisterWindowFun.js:2-14`。运行态为 `${formID}-${props.base.key}-form`，设计态为 `${formID}-${key}-design`。`formID` 取 `modelContainer.paramsMap.get('formID')`。
- 稳定 id 候选：`#{compMark}`、`#{compMark}-input`、`.{compMark}-container`、`.{compMark}-popup`。**各组件使用方式不同，见各节。** 带 `uuid` 的 id/类名每次加载随机，不可作定位依据。
- 标签（`showLabelText`）均由组件自己渲染，不依赖外部 label 控件。`isShowLabel` 默认 false。`labelPosition` 取值 inside/left/top（Currency、PaymentUnit、InterestRateInput 及 PanuiHelpComp 系默认 `inside`，`template/PanuiHelpComp/staticMembers.js:100-111`）。
  - inside：标签文字在控件内部左侧，值非空时再追加「：」。
  - top：独立 `div` 在控件之前（同一外层 div 内的前一个兄弟）。
  - left：独立 `div`，文字带「：」，是控件的前一个兄弟。
  - 必填标记为标签 div 内的 `<i class="required-icon">*</i>`，在文字之前。FormRadio、PriceInput、AmountComp 不支持 inside（见各节）。
- 值与数据集：所有组件通过 `currentRowSet.putValueWithEvent('<数据集>.<列>', 值, ...)` 回写，列标识由 `dataSetID`/`dataSetColID` 配置决定。
- 禁用：`state.disabled = props.edit != undefined ? !props.edit : false`（各组件构造器均如此）。
- 必填红框：antd `status="error"` 或自定义 `#FF3333` 边框。提示气泡 `ValidateToolTip`（`ui/components/ValidateToolTip/index.jsx`，antd `Tooltip`，`overlayClassName='validate-tooltip-outline'`），`checkType=='containerTip'` 时提示出现在控件下方。

## 一、PanuiHelpComp 系：AccountOpenOrgan / PaymentAccount / CountryArea

三者除字典、列和默认值外完全共用模板，故合并描述。
- 模板：`ui/template/PanuiHelpComp/index.jsx`（渲染）、`PanuiTemplate.tsx`（取值/赋值/字典加载）、`staticMembers.js`（公共属性）。
- 子类只传 `compid`、`idkey`、`nameKey`、`columns`、`filterFields`：

| type | compid | 字典 FkeyDataSetID 默认 | idkey / nameKey | 默认过滤 | 默认 showLabelText | 弹层列 |
|---|---|---|---|---|---|---|
| AccountOpenOrgan | `AccountOpenOrgan` | ZJKHJG（`AccountOpenOrgan/index.tsx:102`） | F_JGBH / F_JGMC（`:20-21`） | `F_SYZT = '1'` | 开户机构 | 编号、名称，可选 F_NAME_SHORT（开关「是否开启银行简称」`:85-92`） |
| PaymentAccount | `PaymentAccount` | ZJZHXX（`PaymentAccount/index.tsx:92`） | F_ZH / F_KHJGMC，`onlyShowId`（`:20-22`） | `F_ZHZT = '1'` | 银行付款账号 | 账号、开户行 |
| CountryArea | `CountryArea` | ZJCOUNTRY（`CountryArea/index.tsx:94`） | F_ISOBH / F_ZHMC（`:20-21`） | `F_IN_USE = '1'` | 国家地区 | 编号、ISO 名称(F_ISOMC)、名称 |

### DOM 结构（`template/PanuiHelpComp/index.jsx`）
```
<Tooltip(ValidateToolTip)>
 <div id="parallel-{key}-{uuid}"                        # :507 id 含 uuid，不稳定
      class="common-parallel-input {compid}-parallel-{key}-{uuid} [select-disabled-box] {compMark}-container">   # :520
   [inside] <div class="comp-search-inside-label [required-label]"><span>[<i.required-icon>*</i>]文本</span>[<span>：</span>]</div>   # :564
   [top]    <div class="comp-form-label"><i.required-icon>*</i><span>文本</span></div>                                              # :578
   [left]   <div class="comp-search-left-label"><i.required-icon>*</i><span>文本：</span></div>                                    # :584
   <div style="position:relative;width:100%">
     <ParallelCode id="{compMark}-input" popupClassName="common-parallel {compMark}-popup {compid}-popup-{key}-{uuid}" .../>        # :590-628
     [F_NAME_SHORT 开启且有值] <div class="bank-short-name">简称：xxx</div>                                                          # :629
```
- 稳定定位：`.{compMark}-container`（外层）、`#{compMark}-input`、弹层 `.{compMark}-popup`。**有 compMark，但需与 `compMark` 精确一致**，设计态会出现 `-design` 后缀。
- ParallelCode 来自 `@panui/fi`（`osp-react-department-webcomps/node_modules/@panui/fi/es/ParallelCode/index.js`），底层是 antd Select（`SelectContain`，`@panui/base`）。内部元素类名：`.ant-select`、`.ant-select-selector`、`.ant-select-selection-item`（单选回显）、`.ant-select-selection-search-input`、`.ant-select-clear`。`id` 传给 antd Select 时通常落在搜索输入框上（antd 行为，**未实测**）。
- 弹层：`popupClassName` 含 `panui-parallel-code common-parallel`（`ParallelCode/index.js:895`），内含 `CommonTable`（行 `tr.ant-table-row`，选中行加 `ant-table-row-selected`，`index.js:643-654`），搜索占位「请输入编号/名称」（`:894`）。弹层是否 portal 到 body：**未确认**（`getPopupContainer` 未传，按 antd 默认应在 body，需实测）。
- 回显：单选时 PanuiHelpComp 用 `selectDom.innerHTML = helpValue.name` 强行把 `.ant-select-selection-item` 改成名称（`index.jsx:393-404`）。**PaymentAccount 因 `onlyShowId` 不改，只显示账号。**

### 赋值与取值
- 用户操作：点击控件或标签（inside 标签 onClick 会 `focus + setOpen(true) + request`，`index.jsx:489-493`）打开下拉面板，单击表格行选中（单选后关闭）；或键盘输入关键词过滤后点行。**无放大镜、无独立弹窗**，不使用 formID/Modal。
- 过滤：`filterListByValue(helpDicts, filterFields)`（`:624`）前端本地过滤，filterFields 即上表列字段；`onSearch` 里 `isManuallyInput` 才有 100ms `setTimeout`（`:457-467`，默认 false）。
- 选中后：`onChange` -> `parent.setValue(value)`（`:50`）-> `PanuiTemplate.setValue`（`PanuiTemplate.tsx:336-371`）写入 `value[insertModelKey]`（默认 `id`，即 idkey 列的值：F_JGBH / F_ZH / F_ISOBH），回显用 name。**数据集里存的是编号，不是名称**。选完约 500ms 后会 `focus()`（`:59-61`）。
- 清空：`allowClear` 的清除按钮触发 `onClear`，值置 `''`（`:140-154`）。
- 脚本赋值 `setObject(bh, mc)`（`PanuiTemplate.tsx:292`）直接写编号并造 `{id,name}` 回显，不依赖字典是否已加载。
- 值格式：字符串，单选为单个编号。多选（`isMultiple`）时为逗号分隔编号（`index.jsx:77`）。

### 异步点
- 字典走 `loadModelData`（`PanuiTemplate.tsx:96-134`），带 `filterDCTCond`、`customOrderBy`（两者可被脚本 `setFilterDCTCond`/`setCustomOrderBy` 动态改，`:139-148`）。**首次展开下拉时才请求**（`requestData` 由 ParallelCode 触发），`setValue` 非空值时也会 `loadDictData()`（`:351`）。自动化需等待下拉表格行出现。
- 滚动加载 `debounce`（ParallelCode `index.js:670`）。
- 级联：组件自身无内置级联。「付款单位 -> 账户」只能通过表单脚本 `setFilterDCTCond` 改账户字典过滤条件实现，**具体试点表单是否这么做：未确认**。
- `defaultSelectFirst`：字典加载后若值为空自动选第一项并触发 `defaultFirstSelect` 脚本（`:239-252, 348-361`），会让“空值”假设失效。

### 只读/必填/禁用
- 禁用：外层 `.select-disabled-box`（`:520`），内部 `.ant-select-disabled`；ParallelCode `disabled`。禁用时不能打开下拉。
- 必填：`enableNotNull` 为真时标签有 `required-icon`（inside 标签还有 `.required-label`）。校验失败：antd Select `status="error"`（`.ant-select-status-error`，`:618`），提示文案经 `tipsContent`（`checkType=='containerTip'`）或外层 Tooltip。
- 只读/展示态（`isDisplay`）：PanuiHelpComp 未见单独展示态分支，**未确认**。

### 标签与定位
- 标签由组件渲染。inside：`.comp-search-inside-label` 是 `.ant-select` 容器之前的兄弟（同一外层 div 内）；top/left 同理。按标签文本定位：找外层 `.common-parallel-input` 里 `.comp-form-label|.comp-search-left-label|.comp-search-inside-label` 的文本，再取同容器内 `#...-input` / `.ant-select`。
- `showLabelText` 默认文字见上表；真实表单可能已改，以表单 JSON 为准。

## 二、PaymentUnit（付款单位）

- 源码：`ui/field/PaymentUnit/index.tsx`（逻辑 + 属性）、`components/PaymentUnit.jsx`（渲染）、`ComponentMethod.ts`（取/赋值）。
- 渲染实体：`@panui/fi` 的 `PacketClassify`（`PaymentUnit.jsx:712-775`），底层同样是 antd Select + 面板，具体内部 DOM **未读 PacketClassify 源码，未确认**。

### DOM
```
<div id="parallel-{key}"                       # :629 id 不含 uuid、不含 compMark，仅含 base.key
     class="common-parallel-input unit-parallel-{key}-{uuid} [select-disabled-box] {compMark}-container">   # :637
   [inside/top/left 标签 div，类名同 PanuiHelpComp: comp-search-inside-label / comp-form-label / comp-search-left-label]  # :672-711
   <PacketClassify id="{compMark}input" popupClassName="common-parallel paymentUnit-select paymentUnit-select-{key}-{uuid} {compMark}-popup" ...>   # :713-715
```
- 注意：输入元素 id 是 `${compMark}input`（**无连字符**），与其他组件的 `${compMark}-input` 不同（`PaymentUnit.jsx:713`）。`parallel-{key}` 在设计器里 key 稳定，可用，但同一表单多个相同 key 的情况（例如多子表）会重复。
- 面板内：`selectDataType=='2'` 时有 antd `Tabs.payment-unit-tabs`，两个标签文字「财资中心」「客户」（`:597-625`）。`isIncludeMember` 且 selectDataType 为 0 或 2 时，面板有两个模式图标：平铺（icon-pingpumoshi）与分级（icon-fenjimoshi）。分级模式下顶部有组织架构 Select（`listChoose`，选项来自 `structureDataSetID`，默认 `ZJ_CUST_GROUP_TYPE`，`index.tsx:847-853`），`groupEdit` 为假时它禁用。

### 赋值与取值
- 用户路径：点击下拉打开面板 -> （可选）切 Tab / 切平铺分级 / 搜索 -> 单击某一行。单选：`onClickRow`（`PaymentUnit.jsx:458-508`）写 `parent.setInputValue(item.id)`、`setInputName(item.name)`，关闭面板。多选：`resolveNormalMultiple/resolveFightMultiple`（`:383-456`）逗号拼接。**不是放大镜弹窗。**
- 值格式：`inputValue` = 单位编号（客户为 `F_DWBH`，财资中心为 `F_JGBH`，`index.tsx:380-393`），多选为逗号分隔字符串。客户/财资中心用 `isCustomer` 区分，不在值里体现（`ComponentMethod.ts:14-39`）。
- 脚本赋值 `setObject(bh, mc, type='0')`（`index.tsx:313`）：type '0' 视为客户。
- 清除：`onClear`（`PaymentUnit.jsx:297-315`）值置空。

### 异步点
- 面板展开时请求 `GetAllPaymentDataService`（`index.tsx:484`），携带 UserId、Language、`isUseLimit`、`GroupType`、`IS_ENABLE_FZJG_DATA`、`ZJDWZD_MDMSelfWhere/ZJFZJG_MDMSelfWhere`（过滤条件）、`controlPermissionScope`。`selectDataType`：0 仅客户、1 仅财资中心、2 两者（`:457-534`）。
- 组织架构下拉另走 `loadStructureDataSet`（`:274`）。
- 切换 Tab、切换平铺/分级都会重新 `requestData`（`PaymentUnit.jsx:121-167`）。
- 级联：无内置。付款单位 -> 付款账户依赖表单脚本，**未确认**。`onSelectChange` 脚本把选中对象传给表单脚本（`:489`）。

### 只读/必填/禁用
- 禁用：外层 `.select-disabled-box`；`disabled` 传入 PacketClassify；内部 `.ant-select-disabled`。
- 必填：标签 `required-icon`；错误 `status="error"`（`:763`）。
- 展示态：未确认。

### 标签
- 标签由组件渲染，位置同上。`showLabelText` 默认值 `index.tsx:736` 附近，具体默认文字**未确认**。

## 三、InterestRateInput（利率汇率输入）

- 源码 `ui/field/InterestRateInput/index.tsx`；样式 `index.less`。

### DOM（`:571-757`）
```
<Tooltip>
 <div id="InterestRateInput-{uuid}"                                  # :587 uuid 随机
      class="InterestRateInput {top-|left-|normal-}InterestRateInput {compMark}-container">   # :588
   [inside] <div class="label-inside-box"><span>文本</span>[<span>：</span>]</div>             # :635
   [top]    <div class="label-top-box"><i.required-icon>*</i><span>文本</span></div>           # :647
   [left]   <div class="label-left-box"><i.required-icon>*</i><span>文本：</span></div>        # :658
   <Input id="{compMark}-input" class="[label-side-input]" .../>                              # :669-722
   <div class="suffix-box"><div class="suffix-unit">%</div>[<div class="suffix-clear"><CloseCircleFilled class="clear-icon"/>]</div>   # :705-720 / :740-755
```
- 内部是 antd `Input`（文本框），**不是 InputNumber**，故 `type` 不是 number，`.ant-input`。外层 `.ant-input-affix-wrapper` 仅在 top/left 并带 suffix 时出现。
- 单位 `%` 是兄弟 div（`suffix-unit`），不在 input 值里。默认单位 `%`（`:783`）。
- 稳定定位：`#{compMark}-input`、`.{compMark}-container`。
- 展示态（`isDisplay` 且 `SYS_DocViewModeDisplayStyle != 'WhiteBgAndBorder'`）：不渲染 Input，改渲染 `div.display-state-box`，空值显示 `--`（`:724-735`）。

### 赋值与取值
- 用户路径：直接键入。`onChange`（`:516-543`）：按精度截断小数，同时写数据集（即时回写，无防抖），触发 `onChange` 脚本。
- `onBlur`（`:480-514`）：`resolveInputValue` 补零到精度（如精度 2，`10 -> 10.00`），校验范围，`setValue`，触发 `onLostFocus` 脚本。**失焦才补零**，自动化断言显示值应在失焦后读取。
- 值格式：展示值是字符串 `"x.xx"`；非数字输入被清空。入库值为 `calcModelValue`（`:324`）：开启 `isAutoConvertEnabled` 时按 `$getUnitConversionRules()` 的 `unit`/`calcRules`/`coefficient` 换算（例如显示 5 入库 0.05，具体规则**未确认**，取决于 unitConversionRules.js），空值入库 `''` 或 `null`（`nullAsDefault`）。
- 清除：悬停时出现 `.clear-icon`，仅在 `showClearIcon` 开启且有值、非禁用时显示。

### 异步点
- 精度：`getEffectivePrecision`（`:44-58`）：优先 `rateType`（利率 `ZJ_LLDECN`，汇率 `ZJ_HLDECN`）对应的系统参数 `po.getEnv(rateType, precision)`，其次组件 `precision`（`:228-237`）。**精度来自系统参数，不是币种。**
- 无远程请求、无 debounce。

### 只读/必填/禁用
- 禁用：`Input disabled`（`:671`）→ `.ant-input-disabled`，外层 border 色变更。
- 必填：标签含 `required-icon`；红框通过样式 `#FF3333`（`:615`）；提示 Tooltip。
- 范围校验失败会保留非法输入但回滚数据集（`:484-497`）。

### 标签
- 标签由组件渲染，`isShowLabel` 默认 false，位置 inside/left/top。inside 的 `.label-inside-box` 是 `Input` 之前的兄弟。

## 四、Currency（币种）

- 源码 `ui/base/Currency/index.tsx`（容器），`ui/components/CurrencyCompent/index.tsx`（下拉本体）。

### DOM（`index.tsx:893-1011`）
```
<Tooltip>
 <div id="currency-{uuid}"                                               # :897
      class="customAccountPeriodClassNames currency-{key}-{uuid} [select-disabled-box] {state.className || compMark+'-container'}">   # :898
   [inside] <div class="comp-search-inside-label [required-label]">…                 # :945
   [top]    <div class="comp-form-label">…                                           # :964
   [left]   <div class="comp-search-left-label">…                                    # :975
   <div class="conDiv common-parallel-input currency-input [currency-disabled-input]">  # :985
     <CurrencyCompent className="{compMark}-input" popupClassName="{compMark}-currency">   # :1001-1002
```
- `CurrencyCompent` 里 `<SelectContain id={className}>`（`CurrencyCompent/index.tsx:497-498`），所以输入元素 id 为 `{compMark}-input`。antd Select 类名同上。
- 下拉面板（`CurrencyCompent/index.tsx:512-560`）：`div.currencyConpent {popupClassName}` -> antd `List`，每项 `List.Item`，文字为 `{code}-{name}`（如 `CNY-人民币`），选中项加 `currency-list-selected`。多选时每项含 antd `Checkbox` 与底部 `.currency-multi-select-confirm`。
- 注意：当 `className` 属性被外层传入时（如 AmountComp 内嵌，见下），外层类名不是 `-container`。

### 赋值与取值
- 用户路径：点击打开下拉，点列表项（单选）；支持搜索（`onSearch`，`CurrencyCompent/index.tsx:405`），常用币种分组（`currencyData.COMMON`，`index.tsx:110`）。
- 值：币种代码（如 `CNY`），数据集列由 `dataSetColID` 指定；回显 `{code, name}`。`changeFun`（`Currency/index.tsx:774-807`）写 `inputValue`，触发 `selectedChangedHandler` 脚本，并 `setTimeout(validateField, 0)`。
- 字典：`viewDataSetID` 默认 `ZJBZZD`（`:135`）。币种元素字段含 `F_BZBH`、`F_BZMC`、`F_JEDECN`（金额精度）、`F_JEDECN_CLFS`（进位方式）（参见 `AmountComp/tools.js:86-88`）。

### 异步点
- 打开下拉时 `loadData`（`Currency/index.tsx:368, 830`）才请求 `ZJBZZD` 字典；`DesigneMode` 下不请求。AmountComp 另有自己的 `getCurrencyData`（`AmountComp/index.tsx:342`）。
- 币种影响金额精度的联动在 AmountComp / PriceInput，不在 Currency 自身。

### 只读/必填/禁用
- 禁用：`select-disabled-box` + `currency-disabled-input` + `.ant-select-disabled`。
- 必填：标签 `required-icon`；错误 `status='error'`（`:1009`）。`allowClear` 由属性控制。

### 标签
- 同上，由组件渲染；`isShowLabel` 为真才渲染；inside 标签是 `.conDiv` 之前的兄弟。

## 五、AmountComp（金额含币种）

- 源码 `ui/base/AmountComp/index.tsx`（容器）、`components/AmountComp.jsx`（渲染）、`tools.js`（转换）。

### DOM（`AmountComp.jsx:349-537`）
```
<Tooltip>
 <div id="{compMark}"                                             # :352 外层 id 即 compMark
      class="money-box amount-{key}-{uuid} [comp-set-font-color] [comp-select-font-color]">   # :353
   [top]  <div class="comp-form-label">…</div>                      # :364
   [left] <div class="comp-search-left-label">…                     # :375
   <Space.Compact class="[error]">                                   # :386
      <Tooltip><div class="amount-currency-box [amount-currency-required-error]">        # :445
         <Currency className="{compMark}-currency" popupClassName="{compMark}" isShowLabel=false .../>   # :446-499
      <Tooltip><Input id="{compMark}-input" class="money-box-input|money-box-not-show-clear-input [money-box-disabled-input] [amount-input-required-error]" .../>   # :509-522
   [showAmountWords] <div class="amount-in-words"><span>大写</span></div>   # :527
   [containerTip 且校验失败] <div class="error-text">…</div>                  # :535
```
- 稳定：`#{compMark}`（外层，**唯一一个直接用 compMark 作外层 id 的**）、`#{compMark}-input`（金额）、`#{compMark}-currency`（币种 Select，id 来源 `SelectContain id=className`，推断）。弹层根 div 类名为 `currencyConpent {compMark}`。
- 只支持 top / left 标签（无 inside：币种内部强制 `isShowLabel=false`）。标签 div 是 `Space.Compact` 之前的兄弟。
- 金额 `Input` 是 antd `Input` 文本框，不是 InputNumber。

### 赋值与取值
- 用户路径：先选币种（点币种 Select -> 列表项），再在金额框键入。`isSelectSearch` 为真时币种可搜索。
- 选币种 `changeCurrency`（`AmountComp.jsx:56-81`）：记录当前币种对象 `currentCurrency`，若金额已有值则按新币种重算并 `parent.setValue`，触发 `onChangeSelect` 脚本，写 `currencyColID` 列。
- 金额 `changeInput`（`:243-273`）：按币种 `F_JEDECN`（默认 2）截断小数；有 `maxMoney` 时输入超限即拦截并报错，不更新输入。
- `onInputBlur`（`:275-315`）：去千分符 -> 校验 min/max -> `convertCurrency` 按币种精度与进位方式（`F_JEDECN_CLFS`）取整 -> **显示值带千分符**（`addThousandth`，`tools.js:54`）；写入模型的是去千分符后的数值串（`:292-302`）。Enter 键触发 blur。聚焦时去千分符（`:317-323`）。
- 值格式：金额列 = 去千分符的字符串；币种列 = 币种代码。读取显示值要去掉逗号。
- 未选币种时 `currency` 为空，不做精度/大写转换（`:266`），`convertCurrency` 无 `current` 时直接返回加千分符的原值。

### 异步点
- 币种字典 `ZJBZZD` 经 `LargeDICTService`（`AmountComp/index.tsx:342-365`）加载，打开下拉时 `loadDataSet`（`AmountComp.jsx:478`）。
- 币种 -> 精度联动：选币种后金额小数位立即被截断/进位（见上）。大写金额 `amount-in-words` 随币种与语言（zh_CN / zh_HK / en_US）变化（`tools.js:97-107`）。
- 校验 `setTimeout(...validateField('currencyBlur'),0)`（`:80, 484`）。

### 只读/必填/禁用
- 币种与金额可分别禁用：`selectDisabled`、`inputDisabled`；总禁用 `disabled` 时金额框加 `.money-box-disabled-input`，二者 antd `disabled`。
- 必填：币种与金额分别红框：`.amount-currency-required-error`（币种）、`.amount-input-required-error`（金额）；`Space.Compact` 上 `.error` 表示整体错误（`:386`）。

## 六、PriceInput（价格）

- 源码 `ui/field/PriceInput/index.tsx`（逻辑）、`components/PriceInput.jsx`（渲染）、`register.tsx`（属性）。

### DOM（`PriceInput.jsx:25-139`）
```
<Tooltip>
 <div id="PriceInput-{uuid}" class="price-input [PriceInput-{uuid}-allowClear]">     # :28-29 id 随机，**无 compMark、无 -container**
   [top] <div style="display:flex;height:24px"> [<i style="color:red">*</i>] <span>标签文本</span></div>   # :37-52 无 className，纯内联样式
   showCurrency 为真: <Space.Compact><antd Select showSearch .../><antd Input .../></Space.Compact>        # :93-121
   否则: <antd Input .../>                                                                                  # :122-136
```
- **PriceInput 没有稳定 id**：外层 id 含 `uuid`；`Select` 与 `Input` 都没有传 id；必填星号是内联红色 `<i>`，无 `required-icon` 类。按 label 文本（`span`）定位，再取其同外层 div 下的 `.ant-input`（金额）、`.ant-select`（币种，仅 `showCurrency`）。
- 只支持 `isShowLabel` 的 top 标签（`getShowLabelType` 返回 '3' 或 '1'，`index.tsx:122-124`）。

### 赋值与取值
- 币种：antd 单选 Select，直接选下拉 `.ant-select-item-option`；`optionLabelProp="value"` 所以选后框内只显示代码（如 `USD`），下拉项显示 `代码-名称`（`index.tsx:305-326`）。选项来自 `ZJBZZD`、`F_SYZT=='1'`，在 `componentDidMount` 加载（`:345`）。`dropdownStyle minWidth:max-content`。
- 价格：键入；`onChangeInput`（`index.tsx:527-547`）按 `pricePrecision` 截断小数并即时写数据集；`onBlurInput`（`:507-524`）补零到精度（精度 2: `10 -> 10.00`），触发 `onLostFocus`。
- 值格式：字符串，小数位数由 `pricePrecision` 定。

### 异步点
- 精度：`getInvestmentTypePrecision`（`:266-303`）调用全局 `window.getInvestmentTypePrecision({EXCH_NO, INV_TYPE, CCY, INV_ID})`，取 `precPrice`。**精度依赖同一行的交易所列(exchangeColID)、投资类型列(investmentTypeColID)、币种(currencyColID)、资产名称列(assetIDColID)**，这些列变化时重算（`:464, 487, 552`）。所以改价格前应先填这四个字段，否则精度为初始 0（`:75`）：小数会被截断成整数。
- 币种切换：`onCurrencyChange`（`:550-556`）写币种列、重算精度，触发 `onCurrencyChange` 脚本。

### 只读/必填/禁用
- 禁用：`disabled` 同时禁用 Select 和 Input；`currencyDisabled` 只禁用币种。`.ant-input-disabled` / `.ant-select-disabled`。
- 必填：红色内联星号；红框/提示靠 `ValidateToolTip`。具体错误态 DOM 类名**未确认**。
- 清除：`showClearIcon && !disabled` 时用 antd `allowClear`，悬停可见（`:23, 55-58`），无值时隐藏。

## 七、FormRadio（单选框）

- 重要澄清：`type: 'FormRadio'` 同时在两个文件声明：
  - `osp-react-designer-webcomps/src/ui/FormRadioButtonGroup.tsx:346`（通用控件，01 文档里叫 FormRadioButtonGroup）。
  - `osp-react-department-webcomps/src/ui/base/DepFormRadio/index.tsx:264`。
  - 前者在 `osp-react-designer-webcomps/src/ui/index.ts:32,149` 中被**注释掉**（不导出），而 `osp-react-department-webcomps/src/ui/index.ts:54,121` 导出 `DepFormRadio`。因此运行时 `FormRadio` 实际渲染的应是 **DepFormRadio**（继承 FormRadioButtonGroup，`DepFormRadio/index.tsx:26`）。**不是不同 type，而是同 type 的部门版覆盖。** 注册优先级的运行期验证：未确认。

### DOM（`DepFormRadio/index.tsx:115-256`）
```
<Tooltip>
 <div style="width:100%">
   <Radio.Group id="{compMark}" class="dep-radio-{uuid} [comp-set-font-color]" style="display:inline-flex|block">   # :126-133 / :193-200
      [top]  <div class="comp-form-label"><i.required-icon>*</i><span>文本</span></div>    # :141 / :208
      [left] <div class="comp-search-left-label"><i.required-icon>*</i><span>文本：</span></div>   # :152 / :219
      <Space direction="horizontal|vertical">  ->  <Radio value="…" class="ant-radio-wrapper">label</Radio> ...   # :230-252
```
- `Radio` 来自 `osp-react-basecomps` 的 `FormRadio`（`:12`），行为同 antd Radio。`optionType=='button'` 时用 `Radio.Button`。
- 稳定：`#{compMark}`（Radio.Group 本身，**注意 id 在 group 元素上**）。标签 div 在 **Radio.Group 内部**（`Radio.Group` 的子节点，而非兄弟），位置在 `Space` 之前。
- 不支持 inside 标签（`getShowLabelType` 只有 top/left，`:52-64`）。
- 选项：`options[{label,value,disable}]`；排列模式 `direction=='arrange'` 为 `rowCount × colCount` 网格（嵌套 Space，`:164-190`）。

### 赋值与取值
- 用户路径：直接点击某选项的 radio 或文字。`changeFun`（`:93-113`）：`setValue(val)`、触发 `selectChanged` 脚本、`validateField()`。
- 值：`options[].value` 的字符串（`(item.value+'').trim()` 比较，`:119, 172`）。数据集内为选项 value，不是 label。
- 禁用：整体 `disabled`（`Radio.Group disabled`）+ 选项级 `item.disable=='1'`。
- 必填：标签 `required-icon`；错误提示靠 `ValidateToolTip`。
- 异步：选项为静态 `options`，另有数据集型选项源属性（`type: 'tableSelect'` 的多个属性，`:451-470`），具体加载细节**未确认**（继承基类 FormRadioButtonGroup）。

## 未确认清单

1. 所有 DOM 均来自源码推断，未在浏览器核对，特别是 antd Select 的 `id` 落点、`@panui/fi` ParallelCode/PacketClassify 面板内部类名。
2. PacketClassify（PaymentUnit 面板）内部 DOM 与行类名；ParallelCode 弹层 `getPopupContainer`（是否 portal 到 `body`、是否在 `#ifc-body` 下，CSS 用了 `#ifc-body ...`，推测在其内）。
3. 「付款单位 -> 付款账户」级联：模板内无内置，是否由表单脚本实现（`setFilterDCTCond`）需看具体试点表单脚本。
4. InterestRateInput 的 `isAutoConvertEnabled`、unitConversionRules 的具体系数；`rateType` 对应系统参数实际值。
5. PaymentUnit、AccountOpenOrgan 等 `showLabelText` 真实表单里的文字；PaymentUnit 默认文字。
6. FormRadio 运行时是否确由 DepFormRadio 注册生效；数据集型选项源的加载方式。
7. PanuiHelpComp 系是否有只读（展示态）分支；PriceInput 校验失败时的 DOM 类名。
8. AmountComp 内嵌 Currency 的 Select id 实际值（推断为 `{compMark}-currency`）。
9. `getInvestmentTypePrecision` 全局函数的数据来源（`window.getInvestmentTypePrecision`，未追到定义）。

## 对自动化的难点

1. **定位 id 不统一**：AccountOpenOrgan/PaymentAccount/CountryArea 外层 id 带 `uuid`（`parallel-{key}-{uuid}`）；PaymentUnit 为 `parallel-{key}`；PriceInput `PriceInput-{uuid}`；InterestRateInput `InterestRateInput-{uuid}`；Currency `currency-{uuid}`。只有 AmountComp（`#{compMark}`）、DepFormRadio（`#{compMark}` 在 Radio.Group 上）、以及各组件的 `.{compMark}-container` / `#{compMark}-input` 是稳定的（PaymentUnit 输入 id 是 `{compMark}input` 无连字符，PriceInput 没有）。需按组件 type 建立定位表，不可统一一条规则。
2. **标签位置不统一**：标签是兄弟 div（inside/top/left），FormRadio 的标签在 Radio.Group 内部，PriceInput 的标签无 class。按标签文本找控件需分组件处理，且 inside 标签文字后有「：」条件出现。
3. **下拉不是 antd 标准 Select**：ParallelCode/PacketClassify 是表格式面板（需点行而非 `.ant-select-item`），Currency 是 `List` 面板，只有 PriceInput 是标准 antd Select。需分别封装「选择」动作；多选需点确认。
4. **异步**：下拉首次展开才拉字典，需等行出现再点；搜索是前端本地过滤；PaymentUnit 切 Tab/模式会重新请求。
5. **回显 vs 存值**：存的是编号（F_JGBH、F_ZH、F_ISOBH、币种代码），界面显示名称（PaymentAccount 只显示账号）；断言须区分。AmountComp 显示带千分符，InterestRateInput/PriceInput 失焦才补零。
6. **精度与联动**：金额精度来自币种 `F_JEDECN`；利率精度来自系统参数；价格精度来自同一行的交易所/投资类型/币种/资产。赋值顺序错会截断小数（PriceInput 精度初始 0）。
7. **只读/禁用多形态**：`select-disabled-box`、`.ant-select-disabled`、`.ant-input-disabled`、`.money-box-disabled-input`、InterestRateInput 展示态为 `.display-state-box` 且无 input，需分别判断。
8. **同 type 双实现**：FormRadio 的两个声明需以运行时实际 DOM（`dep-radio-` 前缀）验证。
