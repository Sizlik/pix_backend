from manager.moysklad import CounterpartyManager, CounterpartyRepository, CounterpartyReportManager, \
    CounterpartyReportRepository, ProductFolderRepository, ProductFolderManager, ProductManager, ProductRepository, \
    CustomerOrderManager, CustomerOrderRepository, InvoiceOutManager, InvoiceOutRepository


async def get_counterparty_manager():
    return CounterpartyManager(CounterpartyRepository())


async def get_counterparty_report_manager():
    return CounterpartyReportManager(CounterpartyReportRepository())


async def get_product_folder_manager():
    return ProductFolderManager(ProductFolderRepository())


async def get_product_manager():
    return ProductManager(ProductRepository())


async def get_customer_order_manager():
    return CustomerOrderManager(CustomerOrderRepository())


async def get_invoice_out_manager():
    return InvoiceOutManager(InvoiceOutRepository())
